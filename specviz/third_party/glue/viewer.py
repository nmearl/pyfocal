# This is a data viewer for glue data objects that have a spectral axis. For
# more information about how this viewer is written, see the following
# documentation page:
#
# Writing a custom viewer for glue with Qt
# http://docs.glueviz.org/en/latest/customizing_guide/qt_viewer.html

import os
from collections import OrderedDict

from glue.core import Component, Data
from glue.core.coordinates import coordinates_from_header
from glue.core.data_combo_helper import ComponentIDComboHelper
from glue.core.exceptions import IncompatibleAttribute
from glue.external.echo import (CallbackProperty, SelectionCallbackProperty,
                                keep_in_sync)
from glue.external.echo.qt import autoconnect_callbacks_to_qt
from glue.utils.qt import load_ui
from glue.viewers.common.layer_artist import LayerArtist
from glue.viewers.common.qt.data_viewer import DataViewer
from glue.viewers.common.state import LayerState, ViewerState
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QMdiArea, QMessageBox, QWidget, QAction
import numpy as np
import logging

from .utils import glue_data_has_spectral_axis, glue_data_to_spectrum1d
from ...app import Application
from ...widgets.workspace import Workspace
from .operation_handler import SpectralOperationHandler
from ...core.hub import Hub

__all__ = ['SpecvizDataViewer']

FUNCTIONS = OrderedDict([('maximum', 'Maximum'),
                         ('minimum', 'Minimum'),
                         ('mean', 'Mean'),
                         ('median', 'Median'),
                         ('sum', 'Sum')])


class SpecvizViewerState(ViewerState):
    pass

class SpecvizLayerState(LayerState):
    """

    """
    color = CallbackProperty(docstring='The color used to display the data')
    alpha = CallbackProperty(docstring='The transparency used to display the data')
    linewidth = CallbackProperty(1, docstring='The width of the line for the data')

    attribute = SelectionCallbackProperty(docstring='The attribute to use for the spectrum')
    statistic = SelectionCallbackProperty(docstring='The statistic to use to collapse data')

    def __init__(self, viewer_state=None, **kwargs):

        super(SpecvizLayerState, self).__init__(viewer_state=viewer_state, **kwargs)

        self.color = self.layer.style.color
        self.alpha = self.layer.style.alpha

        self._sync_color = keep_in_sync(self, 'color', self.layer.style, 'color')
        self._sync_alpha = keep_in_sync(self, 'alpha', self.layer.style, 'alpha')

        self._att_helper = ComponentIDComboHelper(self, 'attribute')
        self.add_callback('layer', self._on_layer_change)
        self._on_layer_change()

        SpecvizLayerState.statistic.set_choices(self, list(FUNCTIONS))
        SpecvizLayerState.statistic.set_display_func(self, FUNCTIONS.get)

    def _on_layer_change(self, *args):
        if self.layer is None:
            self._att_helper.set_multiple_data([])
        else:
            self._att_helper.set_multiple_data([self.layer])


class SpecvizLayerArtist(LayerArtist):
    """

    """
    _layer_state_cls = SpecvizLayerState

    def __init__(self, specviz_window, *args, **kwargs):

        super(SpecvizLayerArtist, self).__init__(*args, **kwargs)

        self.specviz_window = specviz_window
        self.plot_widget = self.specviz_window.current_plot_window.plot_widget

        self.state.add_callback('attribute', self.update)
        self.state.add_callback('statistic', self.update)

        self.state.add_callback('zorder', self.update_visual)
        self.state.add_callback('visible', self.update_visual)
        self.state.add_callback('color', self.update_visual)
        self.state.add_callback('alpha', self.update_visual)
        self.state.add_callback('linewidth', self.update_visual)

        self.data_item = None

    def remove(self):
        """

        """
        if self.data_item is not None:
            self.specviz_window.model.remove_data(self.data_item.identifier)
            self.data_item = None

    def clear(self):
        """

        """
        self.remove()

    def redraw(self):
        """

        """
        pass

    @property
    def plot_data_item(self):
        """
        Get the PlotDataItem corresponding to this layer artist.
        """
        if self.data_item is None:
            return None
        else:
            return self.plot_widget.proxy_model.item_from_id(self.data_item.identifier)

    def update_visual(self, *args, **kwargs):
        """

        Parameters
        ----------
        args
        kwargs
        """
        plot_data_item = self.plot_data_item
        if plot_data_item is not None:
            plot_data_item.visible = self.state.visible
            plot_data_item.zorder = self.state.zorder
            plot_data_item.width = self.state.linewidth
            plot_data_item.color = self.state.layer.style.color

    def update(self, *args, **kwargs):
        """

        Parameters
        ----------
        args
        kwargs

        Returns
        -------

        """
        if self.state.layer is None or self.state.attribute is None:
            return

        try:
            spectrum = glue_data_to_spectrum1d(self.state.layer, self.state.attribute, statistic=self.state.statistic)
        except IncompatibleAttribute:
            self.disable_invalid_attributes(self.state.attribute)
            return

        self.enable()

        if self.data_item is None:
            self.data_item = self.specviz_window.model.add_data(spectrum, name=self.state.layer.label)
            self.plot_widget.add_plot(self.plot_data_item, visible=True, initialize=True)
        else:
            self.plot_data_item.data_item.set_data(spectrum)
            # FIXME: we shouldn't have to call update_data manually
            self.plot_data_item.set_data()

        self.update_visual()


class SpecvizViewerStateWidget(QWidget):
    """

    """
    def __init__(self, viewer_state=None, session=None):

        super(SpecvizViewerStateWidget, self).__init__()

        self.ui = load_ui('viewer_state.ui', self,
                          directory=os.path.dirname(__file__))

        self.viewer_state = viewer_state
        autoconnect_callbacks_to_qt(self.viewer_state, self.ui)


class SpecvizLayerStateWidget(QWidget):
    """

    """
    def __init__(self, layer_artist):

        super(SpecvizLayerStateWidget, self).__init__()

        self.ui = load_ui('layer_state.ui', self,
                          directory=os.path.dirname(__file__))

        connect_kwargs = {'alpha': dict(value_range=(0, 1))}

        autoconnect_callbacks_to_qt(layer_artist.state, self.ui, connect_kwargs)

class SpecvizDataViewer(DataViewer):
    """

    """
    LABEL = 'SpecViz viewer'
    _state_cls = SpecvizViewerState
    _options_cls = SpecvizViewerStateWidget
    _layer_style_widget_cls = SpecvizLayerStateWidget
    _data_artist_cls = SpecvizLayerArtist
    _subset_artist_cls = SpecvizLayerArtist
    _inherit_tools = False
    tools = []
    subtools = {}

    def __init__(self, *args, layout=None, **kwargs):
        # Load specviz plugins
        Application.load_local_plugins()

        super(SpecvizDataViewer, self).__init__(*args, **kwargs)
        self.statusBar().hide()

        # Instantiate workspace widget
        self.current_workspace = Workspace()
        self.hub = Hub(self.current_workspace)

        # Store a reference to the cubeviz layout instance
        self._layout = layout

        # Add an initially empty plot window
        self.current_workspace.add_plot_window()

        self.setCentralWidget(self.current_workspace)

        self.options.gridLayout.addWidget(self.current_workspace.list_view)

        # When a new data item is added to the specviz model, create a new
        # glue data component and add it to the glue data list
        # self.current_workspace.model.data_added.connect(self.reverse_add_data)

        self.current_workspace.mdi_area.setViewMode(QMdiArea.SubWindowView)
        self.current_workspace.current_plot_window.setWindowFlags(Qt.FramelessWindowHint)
        self.current_workspace.current_plot_window.showMaximized()

    def reverse_add_data(self, data_item):
        """
        Adds data from specviz to glue.

        Parameters
        ----------
        data_item : :class:`specviz.core.items.DataItem`
            The data item recently added to model.
        """
        new_data = Data(label=data_item.name)
        new_data.coords = coordinates_from_header(data_item.spectrum.wcs)

        flux_component = Component(data_item.spectrum.flux,
                                   data_item.spectrum.flux.unit)
        new_data.add_component(flux_component, "Flux")

        disp_component = Component(data_item.spectrum.spectral_axis,
                                   data_item.spectrum.spectral_axis.unit)
        new_data.add_component(disp_component, "Dispersion")

        if data_item.spectrum.uncertainty is not None:
            uncert_component = Component(data_item.spectrum.uncertainty.array,
                                         data_item.spectrum.uncertainty.unit)
            new_data.add_component(uncert_component, "Uncertainty")

        self._session.data_collection.append(new_data)

    def add_data(self, data):
        """

        Parameters
        ----------
        data

        Returns
        -------

        """
        if not glue_data_has_spectral_axis(data):
            QMessageBox.critical(self, "Error", "Data is not a 1D spectrum",
                                 buttons=QMessageBox.Ok)
            return False
        return super(SpecvizDataViewer, self).add_data(data)

    def add_subset(self, subset):
        """

        Parameters
        ----------
        subset

        Returns
        -------

        """
        if not glue_data_has_spectral_axis(subset):
            QMessageBox.critical(self, "Error", "Subset is not a 1D spectrum",
                                 buttons=QMessageBox.Ok)
            return False
        return super(SpecvizDataViewer, self).add_subset(subset)

    def get_layer_artist(self, cls, layer=None, layer_state=None):
        """

        Parameters
        ----------
        cls
        layer
        layer_state

        Returns
        -------

        """
        return cls(self.current_workspace, self.state, layer=layer, layer_state=layer_state)

    def initialize_toolbar(self):
        """

        """
        super().initialize_toolbar()

        # Find all actions in the default specviz tool bar, sans ones that
        # allow the user to load or delete data. Add these to the glue-generated
        # tool bar.
        for act in self.current_workspace.main_tool_bar.actions()[6:]:
            self.toolbar.addAction(act)

        self.toolbar.addSeparator()

        for act in self.current_workspace.current_plot_window.tool_bar.actions():
            self.toolbar.addAction(act)

        # Hide the main tool bar in favor of the glue-generated one
        self.current_workspace.main_tool_bar.hide()

        # Hide the main tool bar in favor of the glue-generated one
        self.current_workspace.current_plot_window.tool_bar.hide()

        # Show labels in the tool bar
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        # Hide the tabs of the mdiarea in specviz.
        self.current_workspace.mdi_area.setViewMode(QMdiArea.SubWindowView)
        self.current_workspace.current_plot_window.setWindowFlags(Qt.FramelessWindowHint)
        self.current_workspace.current_plot_window.showMaximized()

        # Create operation actions
        act = QAction("Simple Linemap", self)
        act.triggered.connect(self._create_simple_linemap)

        self.current_workspace.main_tool_bar.addAction(act)

        act = QAction("Fitted Linemap", self)
        act.triggered.connect(self.create_fitted_linemap)

        self.current_workspace.main_tool_bar.addAction(act)

    def _create_simple_linemap(self):

        def threadable_function(data, tracker):
            out = np.empty(shape=data.shape)
            mask = self.hub.region_mask

            for x in range(data.shape[1]):
                for y in range(data.shape[2]):
                    out[:, x, y] = np.sum(data[:, x, y][mask])
                    tracker()

            return out

        spectral_operation = SpectralOperationHandler(
            data=self.layers[0].state.layer,
            function=threadable_function,
            operation_name="Simple Linemap",
            component_id=self.layers[0].state.attribute,
            layout=self._layout,
            ui_settings={
                'title': "Simple Linemap Operation",
                'group_box_title': "Choose the component to use for linemap "
                                   "generation",
                'description': "Sums the values of the chosen component in the "
                               "range of the current ROI in the spectral view "
                               "for each spectrum in the data cube."})

        spectral_operation.exec_()

    def create_fitted_linemap(self):

        def threadable_function(data, tracker):
            from astropy.modeling.fitting import LevMarLSQFitter

            out = np.empty(shape=data.shape)
            mask = self.hub.region_mask

            # Check to see if the model fitting plugin is loaded
            model_editor_plugin = self.current_workspace._plugin_bars.get("Model Editor")

            if model_editor_plugin is None:
                logging.error("Model editor plugin is not loaded.")
                return

            spectral_axis = self.hub.plot_item.spectral_axis
            model = model_editor_plugin.model_tree_view.model().evaluate()

            for x in range(data.shape[1]):
                for y in range(data.shape[2]):
                    flux = data[:, x, y].value

                    fitter = LevMarLSQFitter()
                    fit_model = fitter(model,
                                       spectral_axis[mask],
                                       flux[mask])

                    new_data = fit_model(spectral_axis)

                    out[:, x, y] = new_data

                    tracker()

            return out

        spectral_operation = SpectralOperationHandler(
            data=self.layers[0].state.layer,
            function=threadable_function,
            operation_name="Fitted Linemap",
            component_id=self.layers[0].state.attribute,
            layout=self._layout,
            ui_settings={
                'title': "Fitted Linemap Operation",
                'group_box_title': "Choose the component to use for linemap "
                                   "generation",
                'description': "Fits the current model to the values of the "
                               "chosen component in the range of the current "
                               "ROI in the spectral view for each spectrum in "
                               "the data cube."})

        spectral_operation.exec_()
