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

import cbor2
from datetime import datetime, date
from decimal import Decimal
import json
import sys
import traceback
import uuid

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electrum.bitcoin import TYPE_ADDRESS
from electrum.commands import NameAlreadyExistsError
from electrum.i18n import _
from electrum.names import (format_name_identifier, format_name_identifier_split, get_domain_records,
                            identifier_to_namespace, name_from_str, name_to_str, Encoding, 
                            validate_A_record, validate_domains, validate_DNSSEC, validate_TLS, 
                            validate_SSH, validate_SRV, validate_IMPORT)
from electrum.network import TxBroadcastError, BestEffortRequestFailed
from electrum.util import NotEnoughFunds, NoDynamicFeeEstimates
from electrum.wallet import InternalAddressCorruption

from .forms.configurenamedialog import Ui_ConfigureNameDialog
from .paytoedit import PayToEdit
from .configure_dns_dialog import show_configure_dns
from .util import MessageBoxMixin

dialogs = []  # Otherwise python randomly garbage collects the dialogs...


def cbor_to_diagnostic(obj) -> str:
    """Convert a decoded CBOR object to CBOR Diagnostic Notation (RFC 8949 Appendix G)."""
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, bytes):
        return "h'" + obj.hex() + "'"
    if isinstance(obj, str):
        return '"' + obj.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(obj, list):
        items = ", ".join(cbor_to_diagnostic(item) for item in obj)
        return "[" + items + "]"
    if isinstance(obj, dict):
        pairs = ", ".join(
            cbor_to_diagnostic(k) + ": " + cbor_to_diagnostic(v)
            for k, v in obj.items()
        )
        return "{" + pairs + "}"
    if isinstance(obj, cbor2.CBORTag):
        return str(obj.tag) + "(" + cbor_to_diagnostic(obj.value) + ")"
    if isinstance(obj, cbor2.CBORSimpleValue):
        return "simple(" + str(obj.value) + ")"
    # cbor2 auto-decodes some tags into Python types
    if isinstance(obj, datetime):
        return '1("' + obj.isoformat() + '")'
    if isinstance(obj, date):
        return '1004("' + obj.isoformat() + '")'
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return "37(h'" + obj.hex + "')"
    # Fallback
    return repr(obj)


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

            self.accepted.connect(lambda: self.register_and_broadcast(self.identifier, self.ui.dataEditHex.text(), self.ui.transferTo))
        else:
            self.setWindowTitle(_("Reconfigure Name"))

            self.ui.labelSubmitHint.setText(_("Name update will take approximately 10 minutes to 2 hours."))

            self.accepted.connect(lambda: self.update_and_broadcast(self.identifier, self.ui.dataEditHex.text(), self.ui.transferTo))

        self.SubmitHintText = self.ui.labelSubmitHint.text()
        self.ui.labelSubmitHint.setWordWrap(True)

        formatted_name_split = format_name_identifier_split(self.identifier)
        self.ui.labelNamespace.setText(formatted_name_split.category + ":")
        self.ui.labelName.setText(formatted_name_split.specifics)

        self.set_value(value)

        self.namespace = identifier_to_namespace(self.identifier)
        self.namespace_is_dns = self.namespace in ["d", "dd"]

        self.ui.btnDNSEditor.setVisible(self.namespace_is_dns)
        self.ui.btnDNSEditor.clicked.connect(lambda: show_configure_dns(name_from_str(self.ui.dataEditHex.text(), Encoding.HEX), self))

        self.configure_name_ascii_lineedit = self.ui.dataEdit
        self.configure_name_ascii_lineedit.textEdited.connect(self.update_value_from_ascii)

        self.configure_name_hex_lineedit = self.ui.dataEditHex
        self.configure_name_hex_lineedit.textEdited.connect(self.update_value_from_hex)

        self.LabelValidJSON = self.ui.labelValidJSON
        self.LabelValidJSON.setWordWrap(True)
        self.configure_name_ascii_lineedit.textChanged.connect(self.validate_json_data)

        # Connect hex changes to CBOR validation
        self.configure_name_hex_lineedit.textChanged.connect(self.validate_cbor_data)

    def set_value(self, value):
        value_hex = name_to_str(value, Encoding.HEX)
        self.ui.dataEditHex.setText(value_hex)
        self.update_value_from_hex()


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

    def register_and_broadcast(self, identifier, value_hex, transfer_to):
        recipient_address = self.get_transfer_address(transfer_to)
        if recipient_address == False:
            return

        name_autoregister = self.main_window.console.namespace.get('name_autoregister')

        try:
            name_autoregister(name_to_str(identifier, Encoding.HEX), value_hex, destination=recipient_address, wallet=self.wallet, name_encoding=Encoding.HEX, value_encoding=Encoding.HEX)
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

    def update_and_broadcast(self, identifier, value_hex, transfer_to):
        recipient_address = self.get_transfer_address(transfer_to)
        if recipient_address == False:
            return

        name_update = self.main_window.console.namespace.get('name_update')
        broadcast = self.main_window.console.namespace.get('broadcast')

        try:
            tx = name_update(name_to_str(identifier, Encoding.HEX), value_hex, destination=recipient_address, wallet=self.wallet, name_encoding=Encoding.HEX, value_encoding=Encoding.HEX)
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

    def update_value_from_ascii(self):
        try:
            value_ascii = self.ui.dataEdit.text()
            value = name_from_str(value_ascii, Encoding.ASCII)
            value_hex = name_to_str(value, Encoding.HEX)
            self.ui.dataEditHex.setText(value_hex)
            self.ui.labelSubmitHint.setText(self.SubmitHintText)
            self.ui.btnDNSEditor.setDisabled(False)
        except Exception as e:
            self.ui.labelSubmitHint.setText(f"{e}")
            self.ui.btnDNSEditor.setDisabled(True)

    def update_value_from_hex(self):
        try:
            value_hex = self.ui.dataEditHex.text()
            value = name_from_str(value_hex, Encoding.HEX)

            self.ui.labelSubmitHint.setText(self.SubmitHintText)
            self.ui.btnDNSEditor.setDisabled(False)
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setDisabled(False)

            try:
                # If parsing the data as CBOR succeeds & data is a dict, return with buttons enabled
                cbor_data = cbor2.loads(value)
                if type(cbor_data) is not dict:
                    # If the data is not a dictionary, dns editor is disabled
                    self.ui.btnDNSEditor.setDisabled(True)
                return
            except Exception:
                pass

            try:
                value_ascii = name_to_str(value, Encoding.ASCII)
                self.ui.dataEdit.setText(value_ascii)
            except Exception as e:
                # Value contains non-ASCII bytes; switch to hex tab.
                # DNS Editor uses ASCII, hence we disable the button.
                self.ui.tabWidget.setCurrentIndex(1)
                self.ui.btnDNSEditor.setDisabled(True)

        except Exception as e:
            self.ui.labelSubmitHint.setText(f"{e}")
            self.ui.btnDNSEditor.setDisabled(True)
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setDisabled(True)

        # As far as I can tell, we don't need to explicitly add the transaction
        # to the wallet, because we're only issuing a single transaction, so
        # there's not much risk of accidental double-spends from subsequent
        # transactions.

    def validate_cbor_data(self):
        """Validate the hex value as CBOR and show diagnostic notation if valid."""
        try:
            value_hex = self.ui.dataEditHex.text()
            if not value_hex:
                self.ui.cborDiagnosticEdit.clear()
                self.ui.labelCborDiagTitle.setVisible(False)
                self.ui.cborDiagnosticEdit.setVisible(False)
                return

            value = name_from_str(value_hex, Encoding.HEX)

            try:
                cbor_data = cbor2.loads(value)
                diagnostic = cbor_to_diagnostic(cbor_data)
                self.ui.cborDiagnosticEdit.setText(diagnostic)
                self.ui.labelCborDiagTitle.setVisible(True)
                self.ui.cborDiagnosticEdit.setVisible(True)
            except Exception:
                # Not valid CBOR — hide the diagnostic display
                self.ui.cborDiagnosticEdit.clear()
                self.ui.labelCborDiagTitle.setVisible(False)
                self.ui.cborDiagnosticEdit.setVisible(False)

        except Exception:
            # Invalid hex
            self.ui.cborDiagnosticEdit.clear()
            self.ui.labelCborDiagTitle.setVisible(False)
            self.ui.cborDiagnosticEdit.setVisible(False)

    def validate_json_data(self):
        address_type_dict = {
            "ip4": "IPv4",
            "ip6": "IPv6",
            "tor": "Tor",
            "i2p": "I2P",
            "freenet": "Freenet",
            "zeronet": "ZeroNet",
        }
        try:
            json_string = self.ui.dataEdit.text()

            if not json_string:
                self.LabelValidJSON.clear()
                return

            records, self.extra_records = get_domain_records(self.ui.labelName.text(),json_string)
            for record in records:
                _, record_type, data = record
                if record_type == "address":
                    if data[0] == "ip4":
                        validate_A_record(data[1], address_type_dict[data[0]])
                    elif data[0] == "ip6":
                        validate_A_record(data[1], address_type_dict[data[0]])
                    elif data[0] == "tor":
                        validate_A_record(data[1], address_type_dict[data[0]])
                    elif data[0] == "i2p":
                        validate_A_record(data[1], address_type_dict[data[0]])
                    elif data[0] == "freenet":
                        validate_A_record(data[1], address_type_dict[data[0]])
                    elif data[0] == "ipfs":
                        # TODO: Implement IPFS validation
                        pass
                    elif data[0] == "ipns":
                        # TODO: Implement IPNS validation
                        pass
                    elif data[0] == "zeronet":
                        validate_A_record(data[1], address_type_dict[data[0]])
                    else:
                        raise ValueError("Unknown address type")
                
                elif record_type == "cname":
                    validate_domains(data)
                elif record_type == "ns":
                    validate_domains(data)
                elif record_type == "ds":
                    validate_DNSSEC(data[3], data[2], data[1])
                elif record_type == "tls":
                    validate_TLS(data)
                elif record_type == "sshfp":
                    validate_SSH(data[0], data[1], data[2])
                elif record_type == "txt":
                    pass
                elif record_type == "srv":
                    validate_SRV(data[0], data[1], data[2], data[3])
                elif record_type == "import":
                    validate_IMPORT(data[0])
                else:
                    raise ValueError("Unknown record type")
            # Check if JSON is compact
            list_of_records = json.loads(json_string)
            compact_json = json.dumps(list_of_records)

            if len(json_string) > len(compact_json):
                raise ValueError("JSON is not compact")

            self.LabelValidJSON.clear()
        except json.JSONDecodeError:
            self.LabelValidJSON.setText("Invalid JSON")
        except Exception as e:
            self.LabelValidJSON.setText(f"{e}")
