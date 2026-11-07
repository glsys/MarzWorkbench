# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.
"""Dockable metadata editor usable alongside Sketcher edit mode."""

from freecad.marz.extension.fc import App, Gui
from freecad.marz.extension.qt import QtCore, QtWidgets
from freecad.marz.feature.svg_sketch import POCKET_SKETCH_NAMES
from freecad.marz.feature.pocket_properties import pocket_elements, set_pocket_properties


class PocketPropertiesDock(QtWidgets.QDockWidget):
    def __init__(self, parent):
        super().__init__('Marz Pocket Properties', parent)
        self.setObjectName('MarzPocketPropertiesDock')
        self._document = None
        self._updating = False
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        self.sources = QtWidgets.QComboBox()
        self.sources.addItem('Body pockets', 'body')
        self.sources.addItem('Headstock pockets', 'headstock')
        layout.addWidget(self.sources)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['SVG ID', 'Start (mm)', 'End (mm)', 'Target'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        form = QtWidgets.QFormLayout()
        self.start = QtWidgets.QDoubleSpinBox()
        self.end = QtWidgets.QDoubleSpinBox()
        for control in (self.start, self.end):
            control.setDecimals(3)
            control.setRange(0, 100000)
            control.setSuffix(' mm')
        form.addRow('Start depth', self.start)
        form.addRow('End depth', self.end)
        self.target = QtWidgets.QComboBox()
        self.target.addItem('Both', '')
        self.target.addItem('Top', 't')
        self.target.addItem('Back', 'b')
        form.addRow('Cut target', self.target)
        layout.addLayout(form)
        actions = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton('Apply pocket properties')
        self.refresh_button = QtWidgets.QPushButton('Refresh list')
        self.highlight_button = QtWidgets.QPushButton('Highlight pocket')
        actions.addWidget(self.apply_button)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.highlight_button)
        layout.addLayout(actions)
        self.status = QtWidgets.QLabel('Select a pocket to edit its dimensions.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setWidget(panel)
        self.sources.currentIndexChanged.connect(self.populate)
        self.table.itemSelectionChanged.connect(self._row_changed)
        self.apply_button.clicked.connect(self.apply)
        self.refresh_button.clicked.connect(self.populate)
        self.highlight_button.clicked.connect(self.highlight_selected_pocket)
        self._update_controls(False)

    def open_for_document(self, doc):
        self._document = doc
        self._updating = True
        try:
            selection = Gui.Selection.getSelection()
            selected_names = {obj.Name for obj in selection}
            edit = Gui.activeDocument().getInEdit() if Gui.activeDocument() else None
            edit_name = getattr(getattr(edit, 'Object', None), 'Name', None)
            for category, name in POCKET_SKETCH_NAMES.items():
                if name in selected_names or name == edit_name:
                    self.sources.setCurrentIndex(0 if category == 'body' else 1)
                    break
            else:
                if doc.getObject(POCKET_SKETCH_NAMES['body']) is None:
                    self.sources.setCurrentIndex(1)
        finally:
            self._updating = False
        self.populate()
        self.show()
        self.raise_()
        App.Console.PrintMessage('[Marz Pocket] Properties dock ready (no SVG reimport)\n')

    def _sketch(self):
        if self._document is None:
            return None
        return self._document.getObject(POCKET_SKETCH_NAMES[self.sources.currentData()])

    def _update_controls(self, enabled):
        for widget in (self.start, self.end, self.target, self.apply_button,
                       self.highlight_button):
            widget.setEnabled(enabled)

    def populate(self, *_args):
        if self._updating:
            return
        self._updating = True
        try:
            self.table.setRowCount(0)
            sketch = self._sketch()
            try:
                entries = pocket_elements(sketch)
            except (ValueError, AttributeError, TypeError) as exc:
                self.status.setText(str(exc))
                self._update_controls(False)
                return
            for row, entry in enumerate(entries):
                self.table.insertRow(row)
                for column, value in enumerate((entry['id'],
                        '{:.3f}'.format(entry['start']),
                        '{:.3f}'.format(entry['start'] + entry['depth']),
                        {'': 'Both' if self.sources.currentData() == 'body' else 'Headstock', 't': 'Top', 'b': 'Back'}.get(entry['target'], '?'))):
                    self.table.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
            self.status.setText('{} pockets. Select a row to edit; SVG IDs remain unchanged.'.format(len(entries)))
            self._update_controls(False)
        finally:
            self._updating = False

    def _row_changed(self):
        if self._updating:
            return
        row = self.table.currentRow()
        sketch = self._sketch()
        if row < 0 or sketch is None:
            self._update_controls(False)
            return
        try:
            entry = pocket_elements(sketch)[row]
        except (ValueError, IndexError):
            self._update_controls(False)
            return
        self._update_controls(True)
        self.start.setValue(entry['start'])
        self.end.setValue(entry['start'] + entry['depth'])
        self.target.setCurrentIndex(self.target.findData(entry['target']))
        self.target.setEnabled(self.sources.currentData() == 'body')

    def highlight_selected_pocket(self):
        """Highlight on request, never from a Qt selection-change callback.

        Calling Gui.Selection during row-change notifications can reenter the
        Sketcher task view and stall the interface. In Sketcher edit mode the
        sketch owns selection, so leave it alone.
        """
        sketch = self._sketch()
        row = self.table.currentRow()
        if sketch is None or row < 0:
            return
        gui_doc = Gui.activeDocument()
        if gui_doc is not None and gui_doc.getInEdit() is not None:
            self.status.setText('Finish Sketcher edit mode to highlight pocket edges.')
            return
        try:
            indices = pocket_elements(sketch)[row]['indices']
            Gui.Selection.clearSelection()
            for index in indices:
                Gui.Selection.addSelection(sketch.Document.Name, sketch.Name,
                                           'Edge{}'.format(index + 1))
        except Exception as exc:
            self.status.setText('Pocket highlight unavailable: {}'.format(exc))

    def apply(self):
        sketch = self._sketch()
        row = self.table.currentRow()
        if sketch is None or row < 0:
            return
        entry = pocket_elements(sketch)[row]
        doc = sketch.Document
        gui_doc = Gui.activeDocument()
        # Sketcher owns the active transaction while a sketch is being edited.
        # Avoid opening a second document transaction inside its edit session.
        in_edit_mode = gui_doc is not None and gui_doc.getInEdit() is not None
        if not in_edit_mode:
            doc.openTransaction('Marz Pocket Properties')
        try:
            success = set_pocket_properties(sketch, entry['id'],
                   self.start.value(), self.end.value(), self.target.currentData())
            if not success:
                if not in_edit_mode:
                    doc.abortTransaction()
                self.status.setText('Cutter rebuild failed; previous properties retained. See Report view.')
                return
            doc.recompute()
            if not in_edit_mode:
                doc.commitTransaction()
        except Exception as exc:
            if not in_edit_mode:
                doc.abortTransaction()
            self.status.setText('Invalid pocket properties: {}'.format(exc))
            return
        self.populate()
        self.table.selectRow(row)
        self.status.setText('Saved and rebuilt cutters. Use Update Parts for finished guitar solids.')


_dock = None


def show_pocket_properties():
    global _dock
    doc = App.ActiveDocument
    if doc is None:
        return
    App.Console.PrintMessage('[Marz Pocket] Opening properties dock (no SVG import)\n')
    main = Gui.getMainWindow()
    if _dock is None:
        _dock = PocketPropertiesDock(main)
        App.Console.PrintMessage('[Marz Pocket] Dock constructed\n')
        main.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, _dock)
    _dock.open_for_document(doc)
