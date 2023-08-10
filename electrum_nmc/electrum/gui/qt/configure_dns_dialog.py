#!/usr/bin/env python
#
# Electrum-NMC - lightweight Namecoin client
# Copyright (C) 2012-2019 Namecoin Developers, Electrum Developers
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

from copy import deepcopy
from enum import IntEnum
import json
import sys
import traceback
from typing import Union, List, Dict

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electrum.i18n import _
from electrum.names import add_domain_record, get_domain_records, validate_onion_address, validate_zeronet_address

from .forms.dnsdialog import Ui_DNSDialog
from .forms.dnssubdomaindialog import Ui_DNSSubDomainDialog
from .util import MessageBoxMixin

dialogs = []  # Otherwise python randomly garbage collects the dialogs...

def show_configure_dns(value, parent):
    if value != b"":
        try:
            json.loads(value)
        except json.decoder.JSONDecodeError:
            parent.show_error(_("Current value of name is not valid JSON; please fix this before using the DNS editor."))
            return

    d = ConfigureDNSDialog(value, parent)

    dialogs.append(d)
    d.show()

class ConfigureDNSDialog(QDialog, MessageBoxMixin):
    class Columns(IntEnum):
        DOMAIN = 0
        TYPE = 1
        DATA = 2

    headers = {
        Columns.DOMAIN: _('Domain'),
        Columns.TYPE: _('Type'),
        Columns.DATA: _('Data'),
    }

    TEXT_ADD_SUBDOMAIN = "Add Subdomain…"

    def __init__(self, value, parent):
        QDialog.__init__(self, parent=parent)

        self.name_dialog = parent

        self.ui = Ui_DNSDialog()
        self.ui.setupUi(self)

        self.editing_row = None

        identifier = self.name_dialog.identifier.decode('ascii')
        if self.name_dialog.namespace == "d":
            self.base_domain = identifier[len("d/"):] + ".bit"
        elif self.name_dialog.namespace == "dd":
            self.base_domain = "(…).bit"
        else:
            raise Exception("Identifier '" + identifier + "' is not d/ or dd/")

        # Fill in base domain in instructions.
        self.ui.labelTLSDesc.setText(self.ui.labelTLSDesc.text().replace("example.bit", self.base_domain))

        subdomains = set([self.base_domain])

        records, self.extra_records = get_domain_records(self.base_domain, value)

        subdomains.update([record[0] for record in records])

        self.ui.comboDomain.addItem(_(self.__class__.TEXT_ADD_SUBDOMAIN))

        for domain in subdomains:
            self.add_domain(domain)

        # Default to base domain
        self.ui.comboDomain.setCurrentIndex(0)

        self.ui.comboDomain.activated.connect(self.domain_changed)

        self.ui.listDNSRecords.setModel(QStandardItemModel(self))
        self.ui.listDNSRecords.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.ui.listDNSRecords.setSortingEnabled(True)

        self.ui.listDNSRecords.model().clear()
        self.update_headers(self.__class__.headers)

        # Update byte usage at least once in case there aren't any records to
        # add.
        self.update_byte_usage()

        for idx, record in enumerate(records):
            self.insert_record(idx, record)

        self.ui.btnACreate.clicked.connect(self.create_address_record)
        self.ui.btnCNAMECreate.clicked.connect(self.create_cname_record)
        self.ui.btnNSCreate.clicked.connect(self.create_ns_record)
        self.ui.btnDSCreate.clicked.connect(self.create_ds_record)
        self.ui.btnTLSCreate.clicked.connect(self.create_tls_record)
        self.ui.btnSSHFPCreate.clicked.connect(self.create_sshfp_record)
        self.ui.btnTXTCreate.clicked.connect(self.create_txt_record)
        self.ui.btnSRVCreate.clicked.connect(self.create_srv_record)
        self.ui.btnIMPORTCreate.clicked.connect(self.create_import_record)

        self.ui.btnDeleteRecord.clicked.connect(self.delete_selected_records)
        self.ui.btnEditRecord.clicked.connect(self.edit_selected_record)

        # Connect the textChanged signal of QLineEdit to the validation slot
        self.ui.editAHostname.textChanged.connect(self.validate_input)
        self.ui.error_label.setStyleSheet('border: none')
        self.ui.comboHostType.currentIndexChanged.connect(self.ui.error_label.clear)

        self.accepted.connect(lambda: self.name_dialog.set_value(self.get_value()))

    def add_domain(self, domain):
        domain_reverse = domain.split(".")[::-1]

        combo = self.ui.comboDomain

        for index in range(combo.count()):
            domain_at_index = combo.itemText(index)

            # Duplicate of existing domain.
            if domain == domain_at_index:
                combo.setCurrentIndex(index)
                return

            # "Add Subdomain" item is always at the end.
            if domain_at_index == _(self.__class__.TEXT_ADD_SUBDOMAIN):
                combo.insertItem(index, domain)
                combo.setCurrentIndex(index)
                return

            domain_at_index_reverse = domain_at_index.split(".")[::-1]

            # We've found the right place to insert it.
            if domain_reverse < domain_at_index_reverse:
                combo.insertItem(index, domain)
                combo.setCurrentIndex(index)
                return

    def domain_changed(self, index):
        if self.ui.comboDomain.itemText(index) == _(self.__class__.TEXT_ADD_SUBDOMAIN):
            d = QDialog(parent=self)

            ui = Ui_DNSSubDomainDialog()
            ui.setupUi(d)

            ui.labelDomainName.setText(self.base_domain)

            ui.btnAdd.accepted.connect(lambda: self.add_domain(ui.editSubDomain.text() + "." + self.base_domain))

            dialogs.append(d)
            d.show()

    def get_selected_domain(self):
        return self.ui.comboDomain.currentText()

    def create_address_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        address_type_dict = {
            "IPv4": "ip4",
            "IPv6": "ip6",
            "Tor": "tor",
            "I2P": "i2p",
            "Freenet": "freenet",
            "ZeroNet": "zeronet",
        }

        address_type = address_type_dict[self.ui.comboHostType.currentText()]

        if address_type == "freenet" and self.has_freenet_record(domain):
            self.show_error(domain + _(" already has a Freenet record."))
            return

        if address_type == "zeronet" and self.has_zeronet_record(domain):
            self.show_error(domain + _(" already has a ZeroNet record."))
            return

        address = self.ui.editAHostname.text()

        record = [domain, "address", [address_type, address]]

        self.insert_record(idx, record)

        self.ui.editAHostname.setText("")

    def validate_input(self, address):
        address_type = self.ui.comboHostType.currentText()
        if address_type == "Tor":
            try:
                validate_onion_address(address)
                self.ui.error_label.clear()
            except Exception as e:
                self.ui.error_label.setText(str(e))
        elif address_type == "ZeroNet":
            try:
                validate_zeronet_address(address)
                self.ui.error_label.clear()
            except Exception as e:
                self.ui.error_label.setText(str(e))
        

    def create_cname_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()

        if self.has_cname_record(domain):
            self.show_error(domain + _(" already has a CNAME record."))
            return

        data = self.ui.editCNAMEAlias.text()

        record = [domain, "cname", data]

        self.insert_record(idx, record)

        self.ui.editCNAMEAlias.setText("")

    def create_ns_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        data = self.ui.editNSHosts.text()

        record = [domain, "ns", data]

        self.insert_record(idx, record)

        self.ui.editNSHosts.setText("")

    def create_ds_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        try:
            data = [
                int(self.ui.editDSKeyTag.text()),
                int(self.ui.editDSAlgorithm.text()),
                int(self.ui.editDSHashType.text()),
                self.ui.editDSHash.text(),
            ]
        except ValueError:
            self.show_error(_("The Keytag, Algorithm, and Hashtype must be integers."))
            return

        record = [domain, "ds", data]

        self.insert_record(idx, record)

        self.ui.editDSKeyTag.setText("")
        self.ui.editDSHash.setText("")

    def create_tls_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        # TLS records always use the base domain.
        domain = self.base_domain
        data = self.ui.editTLSData.toPlainText()

        record = [domain, "tls", data]

        self.insert_record(idx, record)

        self.ui.editTLSData.setPlainText("")

    def create_sshfp_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        try:
            data = [
                int(self.ui.editSSHFPAlgorithm.text()),
                int(self.ui.editSSHFPFingerprintType.text()),
                self.ui.editSSHFPFingerprint.text(),
            ]
        except ValueError:
            self.show_error(_("The Algorithm and Fingerprint Type must be integers."))
            return

        record = [domain, "sshfp", data]

        self.insert_record(idx, record)

        self.ui.editSSHFPFingerprint.setText("")

    def create_txt_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        data = self.ui.editTXTData.text()

        record = [domain, "txt", data]

        self.insert_record(idx, record)

        self.ui.editTXTData.setText("")

    def create_srv_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        try:
            data = [
                int(self.ui.editSRVPriority.text()),
                int(self.ui.editSRVWeight.text()),
                int(self.ui.editSRVPort.text()),
                self.ui.editSRVHost.text(),
            ]
        except ValueError:
            self.show_error(_("The Priority, Weight, and Port must be integers."))
            return

        record = [domain, "srv", data]

        self.insert_record(idx, record)

        self.ui.editSRVPriority.setText("")
        self.ui.editSRVWeight.setText("")
        self.ui.editSRVPort.setText("")
        self.ui.editSRVHost.setText("")

    def create_import_record(self):
        model = self.ui.listDNSRecords.model()
        idx = model.rowCount()

        domain = self.get_selected_domain()
        imported_name = self.ui.editIMPORTName.text()
        imported_subdomain = self.ui.editIMPORTSubdomain.text()

        record = [domain, "import", [imported_name, imported_subdomain]]

        self.insert_record(idx, record)

        self.ui.editIMPORTName.setText("")
        self.ui.editIMPORTSubdomain.setText("")

    def has_freenet_record(self, domain):
        for index, record in enumerate(self.get_records()):
            if index == self.editing_row:
                continue

            record_domain, record_type, data = record

            if record_domain == domain and record_type == "address" and data[0] == "freenet":
                return True

        return False

    def has_zeronet_record(self, domain):
        for index, record in enumerate(self.get_records()):
            if index == self.editing_row:
                continue

            record_domain, record_type, data = record

            if record_domain == domain and record_type == "address" and data[0] == "zeronet":
                return True

        return False

    def has_cname_record(self, domain):
        for index, record in enumerate(self.get_records()):
            if index == self.editing_row:
                continue

            record_domain, record_type, data = record

            if record_domain == domain and record_type == "cname":
                return True

        return False

    def insert_record(self, idx, record):
        domain, record_type, data = record

        formatted_domain = domain

        if record_type == "address":
            formatted_record_type = "Address"
            if data[0] == "ip4":
                formatted_data = "IPv4: " + data[1]
            elif data[0] == "ip6":
                formatted_data = "IPv6: " + data[1]
            elif data[0] == "tor":
                formatted_data = "Tor: " + data[1]
            elif data[0] == "i2p":
                formatted_data = "I2P: " + data[1]
            elif data[0] == "freenet":
                formatted_data = "Freenet: " + data[1]
            elif data[0] == "zeronet":
                formatted_data = "ZeroNet: " + data[1]
            else:
                raise Exception("Unknown address type")
        elif record_type == "cname":
            formatted_record_type = "CNAME"
            formatted_data = data
        elif record_type == "ns":
            formatted_record_type = "NS"
            formatted_data = data
        elif record_type == "ds":
            formatted_record_type = "DS"
            formatted_data = json.dumps(data)
        elif record_type == "tls":
            formatted_record_type = "TLS"
            formatted_data = data
        elif record_type == "sshfp":
            formatted_record_type = "SSH"
            formatted_data = json.dumps(data)
        elif record_type == "txt":
            formatted_record_type = "TXT"
            formatted_data = json.dumps(data)
        elif record_type == "srv":
            formatted_record_type = "SRV"
            formatted_data = json.dumps(data)
        elif record_type == "import":
            formatted_record_type = "IMPORT"
            formatted_data = json.dumps(data)
        else:
            raise Exception("Unknown record type")

        labels = [formatted_domain, formatted_record_type, formatted_data]
        record_item = [QStandardItem(x) for x in labels]

        record_item[self.Columns.DOMAIN].setData(domain, Qt.UserRole)
        record_item[self.Columns.TYPE].setData(record_type, Qt.UserRole)
        record_item[self.Columns.DATA].setData(data, Qt.UserRole)

        for cell in record_item:
            cell.setEditable(False)

        self.ui.listDNSRecords.model().insertRow(idx, record_item)

        # Remove the old row if we were editing an existing row.
        if self.editing_row is not None:
            self.ui.listDNSRecords.model().removeRow(self.editing_row)
            self.editing_row = None

        # Show any tabs that were hidden before because we were editing an
        # existing row.
        for tab_index in range(self.ui.tabRecords.count()):
            self.ui.tabRecords.setTabEnabled(tab_index, True)

        self.update_byte_usage()

    def edit_selected_record(self):
        table = self.ui.listDNSRecords

        # Get all selected cells
        cell_indexes = table.selectionModel().selectedIndexes()

        # Get the rows of all selected cells
        rows = set([cell.row() for cell in cell_indexes])

        # Can't edit more than 1 row at once.
        if len(rows) != 1:
            return

        # Get the single row
        row = list(rows)[0]

        model = table.model()

        # Get the indexes for each cell in the row
        row_indexes = [model.index(row, column) for column in range(model.columnCount())]

        # Extract the data from each cell in the row
        single_record = list([model.data(index, Qt.UserRole) for index in row_indexes])

        domain = single_record[0]

        self.ui.comboDomain.setCurrentText(domain)

        # Used to decide which tab to open
        record_type = single_record[1]

        # We only allow editing the data in column 2
        record_data = single_record[2]

        if record_type == "address":
            address_type, address_data = record_data

            address_type_dict = {
                "ip4": "IPv4",
                "ip6": "IPv6",
                "tor": "Tor",
                "i2p": "I2P",
                "freenet": "Freenet",
                "zeronet": "ZeroNet",
            }
            self.ui.comboHostType.setCurrentText(address_type_dict[address_type])

            self.ui.editAHostname.setText(address_data)

            self.force_one_tab(self.ui.tabA)
        elif record_type == "cname":
            self.ui.editCNAMEAlias.setText(record_data)

            self.force_one_tab(self.ui.tabCNAME)
        elif record_type == "ns":
            self.ui.editNSHosts.setText(record_data)

            self.force_one_tab(self.ui.tabNS)
        elif record_type == "ds":
            key_tag, algorithm, hash_type, fingerprint = record_data

            key_tag = str(key_tag)
            algorithm = str(algorithm)
            hash_type = str(hash_type)

            self.ui.editDSKeyTag.setText(key_tag)
            self.ui.editDSAlgorithm.setText(algorithm)
            self.ui.editDSHashType.setText(hash_type)
            self.ui.editDSHash.setText(fingerprint)

            self.force_one_tab(self.ui.tabDS)
        elif record_type == "tls":
            cert_data = record_data

            if not isinstance(cert_data, str):
                self.show_error(_("Only DANE-TA Public Key TLS records can be edited."))
                return

            self.ui.editTLSData.setPlainText(cert_data)

            self.force_one_tab(self.ui.tabTLS)
        elif record_type == "sshfp":
            algorithm, fingerprint_type, fingerprint = record_data

            algorithm = str(algorithm)
            fingerprint_type = str(fingerprint_type)

            self.ui.editSSHFPAlgorithm.setText(algorithm)
            self.ui.editSSHFPFingerprintType.setText(fingerprint_type)
            self.ui.editSSHFPFingerprint.setText(fingerprint)

            self.force_one_tab(self.ui.tabSSHFP)
        elif record_type == "txt":
            self.ui.editTXTData.setText(record_data)

            self.force_one_tab(self.ui.tabTXT)
        elif record_type == "srv":
            priority, weight, port, host = record_data

            priority = str(priority)
            weight = str(weight)
            port = str(port)

            self.ui.editSRVPriority.setText(priority)
            self.ui.editSRVWeight.setText(weight)
            self.ui.editSRVPort.setText(port)
            self.ui.editSRVHost.setText(host)

            self.force_one_tab(self.ui.tabSRV)
        elif record_type == "import":
            imported_name, imported_subdomain = record_data

            self.ui.editIMPORTName.setText(imported_name)
            self.ui.editIMPORTSubdomain.setText(imported_subdomain)

            self.force_one_tab(self.ui.tabIMPORT)
        else:
            raise Exception("Unknown record type")

        self.editing_row = row

    def force_one_tab(self, tab):
        for tab_index in range(self.ui.tabRecords.count()):
            if self.ui.tabRecords.widget(tab_index) == tab:
                self.ui.tabRecords.setTabEnabled(tab_index, True)
                self.ui.tabRecords.setCurrentIndex(tab_index)
            else:
                self.ui.tabRecords.setTabEnabled(tab_index, False)

    def delete_selected_records(self):
        table = self.ui.listDNSRecords

        # Get all selected cells
        cell_indexes = table.selectionModel().selectedIndexes()

        # Get the rows of all selected cells
        rows = set([cell.row() for cell in cell_indexes])

        # Sort the rows in reverse
        rows = sorted(rows, reverse=True)

        # Get the model
        model = table.model()

        # Remove the rows
        for row in rows:
            model.removeRow(row)

        self.update_byte_usage()

    def get_records(self):
        model = self.ui.listDNSRecords.model()

        records = []

        # Iterate through all rows in the table
        for row in range(model.rowCount()):
            # Get the indexes for each cell in the row
            row_indexes = [model.index(row, column) for column in range(model.columnCount())]

            # Extract the data from each cell in the row
            single_record = list([model.data(index, Qt.UserRole) for index in row_indexes])

            records.append(single_record)

        return records

    def get_value(self):
        value = deepcopy(self.extra_records)

        for record in self.get_records():
            add_domain_record(self.base_domain, value, record)

        if value == {}:
            return b""
        else:
            # Use compact, deterministic encoding for JSON
            return json.dumps(value, sort_keys=True, separators=(',', ':')).encode("ascii")

    def update_headers(self, headers: Union[List[str], Dict[int, str]]):
        # headers is either a list of column names, or a dict: (col_idx->col_name)
        if not isinstance(headers, dict):  # convert to dict
            headers = dict(enumerate(headers))
        col_names = [headers[col_idx] for col_idx in sorted(headers.keys())]
        model = self.ui.listDNSRecords.model()
        model.setHorizontalHeaderLabels(col_names)

    def update_byte_usage(self):
        value = self.get_value()
        usage = len(value)
        usage_text = str(usage)

        if usage > 520:
            usage_text = "<span style='color: red;'>\u26A0 " + usage_text + "</span>"

        label = self.ui.labelBytes
        label.setTextFormat(Qt.RichText)
        label.setText(usage_text)

