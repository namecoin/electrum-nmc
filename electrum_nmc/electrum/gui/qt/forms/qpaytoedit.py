from PyQt5.QtWidgets import QCompleter

from ..paytoedit import PayToEdit

import electrum.gui.qt.main_window

from electrum.i18n import _


class QPayToEdit(PayToEdit):
    def __init__(self, parent):
        while not isinstance(parent, electrum.gui.qt.main_window.ElectrumWindow):
            try:
                parent = parent.main_window
            except AttributeError:
                parent = parent.parent

        super().__init__(parent)

        completer = QCompleter()
        completer.setCaseSensitivity(False)
        self.set_completer(completer)
        completer.setModel(self.win.completions)

    def get_outputs(self, is_max):
        self.resolve()

        errors = self.get_errors()
        if errors:
            self.win.show_warning(_("Invalid Lines found:") + "\n\n" + '\n'.join([_("Line #") + f"{err.idx+1}: {err.line_content[:40]}... ({repr(err.exc)})" for err in errors]))

            return None

        if self.is_alias and self.validated is False:
            alias = self.toPlainText()
            msg = _('WARNING: the alias "{}" could not be validated via an additional '
                    'security check, DNSSEC, and thus may not be correct.').format(alias) + '\n'
            msg += _('Do you wish to continue?')
            if not self.win.question(msg):
                return None

        return super().get_outputs(is_max)
