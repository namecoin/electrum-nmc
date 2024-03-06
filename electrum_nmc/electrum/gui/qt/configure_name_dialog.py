#!/usr/bin/env python
#
# Electrum-NMC - lightweight Namecoin client
# Copyright (C) 2012-2018 Namecoin Developers, Electrum Developers
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys
import traceback

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electrum.bitcoin import TYPE_ADDRESS
from electrum.commands import NameAlreadyExistsError
from electrum.i18n import _
from electrum.names import format_name_identifier, format_name_identifier_split, identifier_to_namespace, name_to_str, Encoding
from electrum.network import TxBroadcastError, BestEffortRequestFailed
from electrum.util import NotEnoughFunds, NoDynamicFeeEstimates
from electrum.wallet import InternalAddressCorruption

from .forms.configurenamedialog import Ui_ConfigureNameDialog
from .paytoedit import PayToEdit
from .configure_dns_dialog import show_configure_dns
from .util import MessageBoxMixin

dialogs = []  # Otherwise python randomly garbage collects the dialogs...


def show_configure_name(identifier, value, parent, is_new):
    d = ConfigureNameDialog(identifier, value, parent, is_new)

    dialogs.append(d)
    d.show()


class ConfigureNameDialog(QDialog, MessageBoxMixin):
    def __init__(self, identifier, value, parent, is_new):
        # We want to be a top-level window
        QDialog.__init__(self, parent=None)

        self.main_window = parent
        self.wallet = self.main_window.wallet

        self.ui = Ui_ConfigureNameDialog()
        self.ui.setupUi(self)

        self.identifier = identifier

        if is_new:
            self.setWindowTitle(_("Configure New Name"))

            self.ui.labelSubmitHint.setText(_("Name registration will take approximately 2 to 4 hours."))

            # TODO: handle non-ASCII encodings
            self.accepted.connect(lambda: self.register_and_broadcast(self.identifier, self.ui.dataEdit.text().encode('ascii'), self.ui.transferTo))
        else:
            self.setWindowTitle(_("Reconfigure Name"))

            self.ui.labelSubmitHint.setText(_("Name update will take approximately 10 minutes to 2 hours."))

            # TODO: handle non-ASCII encodings
            self.accepted.connect(lambda: self.update_and_broadcast(self.identifier, self.ui.dataEdit.text().encode('ascii'), self.ui.transferTo))

        formatted_name_split = format_name_identifier_split(self.identifier)
        self.ui.labelNamespace.setText(formatted_name_split.category + ":")
        self.ui.labelName.setText(formatted_name_split.specifics)

        self.set_value(value)

        self.namespace = identifier_to_namespace(self.identifier)
        self.namespace_is_dns = self.namespace in ["d", "dd"]

        self.ui.btnDNSEditor.setVisible(self.namespace_is_dns)
        self.ui.btnDNSEditor.clicked.connect(lambda: show_configure_dns(self.ui.dataEdit.text().encode('ascii'), self))

    def set_value(self, value):
        # TODO: support non-ASCII encodings
        self.ui.dataEdit.setText(value.decode('ascii'))

    def get_transfer_address(self, transfer_to):
        if transfer_to.toPlainText() == "":
            # User left the recipient blank, so this isn't a transfer.
            return None
        else:
            # The user entered something into the recipient text box.

            recipient_outputs = transfer_to.get_outputs(False)
            if recipient_outputs is None:
                return False
            if len(recipient_outputs) != 1:
                self.main_window.show_error(_("You must enter one transfer address, or leave the transfer field empty."))
                return False

            recipient_address = recipient_outputs[0].address
            if recipient_address is None:
                self.main_window.show_error(_("Invalid address ") + recipient_address)
                return False

            return recipient_address

    def register_and_broadcast(self, identifier, value, transfer_to):
        recipient_address = self.get_transfer_address(transfer_to)
        if recipient_address == False:
            return

        name_autoregister = self.main_window.console.namespace.get('name_autoregister')

        try:
            name_autoregister(name_to_str(identifier, Encoding.HEX), name_to_str(value, Encoding.HEX), destination=recipient_address, wallet=self.wallet, name_encoding=Encoding.HEX, value_encoding=Encoding.HEX)
        except NameAlreadyExistsError as e:
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_message(_("Error registering ") + formatted_name + ": " + str(e))
            return
        except (NotEnoughFunds, NoDynamicFeeEstimates) as e:
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_message(_("Error registering ") + formatted_name + ": " + str(e))
            return
        except InternalAddressCorruption as e:
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_error(_("Error registering ") + formatted_name + ": " + str(e))
            raise
        except TxBroadcastError as e:
            msg = e.get_message_for_gui()
            self.main_window.show_error(msg)
        except BestEffortRequestFailed as e:
            msg = repr(e)
            self.main_window.show_error(msg)
        except BaseException as e:
            traceback.print_exc(file=sys.stdout)
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_message(_("Error registering ") + formatted_name + ": " + str(e))
            return

    def update_and_broadcast(self, identifier, value, transfer_to):
        recipient_address = self.get_transfer_address(transfer_to)
        if recipient_address == False:
            return

        name_update = self.main_window.console.namespace.get('name_update')
        broadcast = self.main_window.console.namespace.get('broadcast')

        try:
            # TODO: support non-ASCII encodings
            tx = name_update(identifier.decode('ascii'), value.decode('ascii'), destination=recipient_address, wallet=self.wallet)
        except (NotEnoughFunds, NoDynamicFeeEstimates) as e:
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_message(_("Error creating update for ") + formatted_name + ": " + str(e))
            return
        except InternalAddressCorruption as e:
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_error(_("Error creating update for ") + formatted_name + ": " + str(e))
            raise
        except BaseException as e:
            traceback.print_exc(file=sys.stdout)
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_message(_("Error creating update for ") + formatted_name + ": " + str(e))
            return

        try:
            broadcast(tx)
        except Exception as e:
            formatted_name = format_name_identifier(identifier)
            self.main_window.show_error(_("Error broadcasting update for ") + formatted_name + ": " + str(e))
            return

        # As far as I can tell, we don't need to explicitly add the transaction
        # to the wallet, because we're only issuing a single transaction, so
        # there's not much risk of accidental double-spends from subsequent
        # transactions.

