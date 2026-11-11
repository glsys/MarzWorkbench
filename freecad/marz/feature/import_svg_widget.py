# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileNotice: Part of the Marz addon.

################################################################################
#                                                                              #
#   Copyright (c) 2020 Frank David Martínez Muñoz <mnesarco at gmail.com>      #
#                                                                              #
#   This program is free software: you can redistribute it and / or            #
#   modify it under the terms of the GNU General Public License as             #
#   published by the Free Software Foundation, either version 3 of             #
#   the License, or (at your option) any later version.                        #
#                                                                              #
#   This program is distributed in the hope that it will be useful,            #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU General Public License for more details.                       #
#                                                                              #
#   You should have received a copy of the GNU General Public License          #
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.      #
#                                                                              #
################################################################################

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from freecad.marz.extension.lang import tr
from freecad.marz.feature.files import InternalFile
import freecad.marz.extension.fcui as ui
from freecad.marz.feature.style import FlatIcon, SectionHeader, svg_preview_container_style
from freecad.marz.extension.qt import QSizePolicy, QApplication

@dataclass
class ImportSvgWidget:
    form: Any
    title: str
    file: InternalFile | None = None
    file_property: str | None = None
    height: int = 200
    table: ui.TableWidget | None = None
    preview: ui.SvgImageViewWidget | None = None
    import_action: Callable | None = None
    export_action: Callable | None = None
    last_imported_file: str | None = None
    reimport_btn: ui.QPushButton | None = None
    table_variant: str = 'default'

    def __post_init__(self):
        path, meta = self.file()
        self.last_imported_file = None
        with ui.Section(SectionHeader(self.title)):
            with ui.Col():
                with ui.Row():
                    if self.import_action:
                        btn = ui.button(label=tr("Import"), icon=FlatIcon('import_svg.svg'))
                        btn(self.on_import)
                        btn = ui.button(
                            label=tr("Re-Import"),
                            icon=FlatIcon('reimport_svg.svg'),
                            enabled=False)
                        self.reimport_btn = btn(self.on_reimport)
                    if self.export_action:
                        self._btn_export = ui.button(label=tr("Export"), icon=FlatIcon('export_svg.svg'))(self.export_action)
                    ui.Stretch()

                with ui.Container(styleSheet=svg_preview_container_style()):
                    self.preview = ui.SvgImageView(
                        uri=path,
                        minimumHeight=self.height,
                        maximumHeight=self.height)

                self.table = ui.Table(
                    headers=self.import_table_headers(),
                    rows=self.import_table_rows_from_meta(meta),
                    sizePolicy=(QSizePolicy.Expanding, QSizePolicy.Expanding))


    def on_import(self, reimport: bool = False) -> None:
        self.reimport_btn.setEnabled(False)
        self.reimport_btn.setToolTip("")
        self.import_action(reimport)
        if bool(self.last_imported_file) and Path(self.last_imported_file).exists():
            self.reimport_btn.setEnabled(True)
            self.reimport_btn.setToolTip(tr("Re-Import file: {}").format(self.last_imported_file))

    def on_reimport(self) -> None:
        self.import_action(True)

    def set_export_enable(self, enabled: bool):
        if hasattr(self, '_btn_export'):
            self._btn_export.setVisible(enabled)

    def load(self, title, import_action):
        name = ui.get_open_file(title, tr('Svg files (*.svg)'))
        return self._load(name, import_action) if name else []

    def _load(self, name: str, import_action: Callable[[str], list]):
        self.last_imported_file = name
        with ui.progress_indicator():
            self.preview.setValue(name)
            self.table.setRowCount(0)
            QApplication.processEvents()
            validation = import_action(name)
            if validation:
                rows = self.import_table_rows_from_meta(validation)
                self.table.setRowsData(rows)
            return validation

    def reload(self, title, import_action):
        if self.last_imported_file is None:
            return self.load(title, import_action)
        return self._load(self.last_imported_file, import_action)

    def import_table_headers(self):
        if self.table_variant == 'neck':
            return [tr('Reference'), tr('Validation'), tr('>Fret')]
        if self.table_variant == 'inlay':
            return [tr('Reference'), tr('Validation'), tr('>Fret'), tr('>X'), tr('>Y')]
        return [
            tr('Type'),
            tr('Reference'),
            tr('Validation'),
            tr('>Start'),
            tr('>Depth')]

    @staticmethod
    def _fret_text(value):
        if value is None or value == '':
            return ''
        try:
            return format(float(value), '.12g')
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _validation_text(message):
        # Metadata embedded by older Marz versions stored the fret number in
        # the status itself (for example ``Fret12 Found``).  The new tables
        # have a dedicated Fret column, so keep only the actual status.
        if not isinstance(message, str):
            return message
        import re
        match = re.match(r'^Fret[^ ]+\s+(.+)$', message)
        return match.group(1) if match else message

    def import_table_rows_from_meta(self, meta):
        if not meta:
            return []

        if self.table_variant in ('neck', 'inlay'):
            from freecad.marz.svg_semantics import (
                SemanticSyntaxError, parse_inlay_semantic, parse_neck_semantic)
            parser = parse_neck_semantic if self.table_variant == 'neck' else parse_inlay_semantic
            rows = []
            for row in meta:
                if row.get('kind') == 'Notify':
                    continue
                reference = row.get('reference', '')
                fret = row.get('fret')
                x = row.get('x')
                y = row.get('y')
                if reference and (fret is None or (self.table_variant == 'inlay' and (x is None or y is None))):
                    try:
                        semantic = parser(reference)
                    except SemanticSyntaxError:
                        semantic = None
                    if semantic is not None:
                        if fret is None:
                            fret = semantic.fret
                        if self.table_variant == 'inlay':
                            if x is None:
                                x = semantic.x.display()
                            if y is None:
                                y = semantic.y.display()
                result = [reference, self._validation_text(row.get('message', '')), self._fret_text(fret)]
                if self.table_variant == 'inlay':
                    result.extend([x if x is not None else '', y if y is not None else ''])
                rows.append(tuple(result))
            return rows

        def fmt(x):
            return '' if x is None else f'{x:.2f} mm'
        return [(r['kind'], r['reference'], r['message'], fmt(r['start']), fmt(r['depth']))
                for r in meta if r['kind'] != 'Notify']

