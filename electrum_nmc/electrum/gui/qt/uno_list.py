#!/usr/bin/env python
#
# Electrum-NMC - lightweight Namecoin client
# Copyright (C) 2018-2019 Namecoin Developers
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

from typing import Optional, List
from enum import IntEnum
import sys
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItem, QFont
from PyQt5.QtWidgets import QMenu

from electrum import constants
from electrum.commands import NameUpdatedTooRecentlyError
from electrum.i18n import _
from electrum.names import (
    blocks_remaining_until_confirmations,
    format_name_identifier,
    format_name_value,
    get_queued_firstupdate_from_new,
    name_expiration_datetime_estimate,
    name_semi_expires_in,
    OP_NAME_UPDATE,
)
from electrum.transaction import PartialTxInput
from electrum.util import NotEnoughFunds, NoDynamicFeeEstimates, bh2u
from electrum.wallet import InternalAddressCorruption

from .configure_name_dialog import show_configure_name
from .util import ColorScheme, MONOSPACE_FONT
from .utxo_list import UTXOList

USER_ROLE_TXOUT = 0
USER_ROLE_NAME = 1
USER_ROLE_VALUE = 2


# TODO: It'd be nice if we could further reduce code duplication against
# UTXOList.
class UNOList(UTXOList):
    class Columns(IntEnum):
        NAME = 0
        VALUE = 1
        SEMI_EXPIRES_IN = 2
        STATUS = 3

    headers = {
        Columns.NAME: _("Name"),
        Columns.VALUE: _("Value"),
        Columns.SEMI_EXPIRES_IN: _("Semi-Expires (Est.)"),
        Columns.STATUS: _("Status"),
    }
    filter_columns = [Columns.NAME, Columns.VALUE]
    stretch_column = Columns.VALUE

    def __init__(self, parent):
        super().__init__(parent)
        self.doubleClicked.connect(self.configure_selected_item)

    def update(self):
        self.network = self.parent.network
        super().update()

    def insert_utxo(self, idx, utxo: PartialTxInput):
        txid = utxo.prevout.txid.hex()
        vout = utxo.prevout.out_idx
        name_op = utxo.name_op
        if name_op is None:
            return

        height = utxo.block_height
        header_at_tip = self.network.blockchain().header_at_tip()

        if height is None or height <= 0:
            # TODO: Namecoin: Take into account the fact that transactions may
            # not be mined in the next block.
            blocks_until_mined = 1

            height_estimated = header_at_tip["block_height"] + blocks_until_mined
        else:
            height_estimated = height

        status_tooltip = None

        if "name" not in name_op:
            # utxo is name_new
            queue_item, firstupdate_output = get_queued_firstupdate_from_new(
                self.wallet, txid, vout
            )
            if firstupdate_output is not None:
                if firstupdate_output.name_op is not None:
                    name_op = firstupdate_output.name_op
            expires_in, expires_datetime = None, None
            semi_expires_in, semi_expires_datetime = None, None

            if (
                height is not None and header_at_tip is not None and queue_item is not None
            ):
                sendwhen_depth = queue_item["sendWhen"]["confirmations"]
                blocks_until_firstupdate_sent = blocks_remaining_until_confirmations(
                    height_estimated, header_at_tip["block_height"], sendwhen_depth
                )

                # TODO: Namecoin: Take into account the fact that transactions
                # may not be mined in the next block.
                blocks_until_firstupdate_confirmed = blocks_until_firstupdate_sent + 1

                minutes_remaining_until_firstupdate_confirmed = (
                    10 * blocks_until_firstupdate_confirmed
                )

                status = (
                    _("Registration Pending, ETA %dmin")
                    % minutes_remaining_until_firstupdate_confirmed
                )
            else:
                status = _("Registration Pending")
        else:
            # utxo is name_anyupdate
            if header_at_tip is not None:
                expires_in, expires_datetime = name_expiration_datetime_estimate(
                    height_estimated, self.network.blockchain()
                )
                semi_expires_in, semi_expires_datetime = (
                    name_expiration_datetime_estimate(
                        height_estimated,
                        self.network.blockchain(),
                        blocks_func=name_semi_expires_in,
                    )
                )
            else:
                expires_in, expires_datetime = None, None
                semi_expires_in, semi_expires_datetime = None, None

            if height is not None and height > 0:
                # utxo is confirmed
                if expires_in is not None and expires_in <= 0:
                    status = _("Expired")
                elif semi_expires_in is not None and semi_expires_in <= 0:
                    status = _("Semi-Expired")
                    status_tooltip = _(
                        "This name has stopped resolving because it was not renewed on time.  Renew it ASAP to restore resolution and avoid losing ownership of the name."
                    )
                elif (
                    semi_expires_in is not None and semi_expires_in <= constants.net.NAME_EXPIRATION - constants.net.NAME_SEMI_EXPIRATION
                ):
                    status = _("Semi-Expiring Soon")
                    status_tooltip = _(
                        "This name will stop resolving soon if it is not renewed.  Renew it ASAP to keep it resolving."
                    )
                else:
                    status = _("Confirmed")
            else:
                # utxo is unconfirmed
                if name_op["op"] == OP_NAME_UPDATE:
                    # utxo is name_update
                    status = _("Update Pending")
                else:
                    # utxo is name_firstupdate
                    # TODO: Namecoin: Take into account the fact that
                    # transactions may not be mined in the next block.
                    status = _("Registration Pending, ETA %dmin") % 10

        if "name" in name_op:
            # utxo is name_anyupdate or a name_new that we've queued a name_firstupdate for
            name = name_op["name"]
            formatted_name = format_name_identifier(name)
            value = name_op["value"]
            formatted_value = format_name_value(value)
        else:
            # utxo is a name_new that we haven't queued a name_firstupdate for
            name = None
            formatted_name = ""
            value = None
            formatted_value = ""

        # Copied from electrum.util.format_time.
        # TODO: Patch upstream to avoid this code duplication.
        formatted_expires_datetime = (
            expires_datetime.isoformat(" ")[:-3] if expires_datetime is not None else ""
        )
        formatted_semi_expires_datetime = (
            semi_expires_datetime.isoformat(" ")[:-3]
            if semi_expires_datetime is not None
            else ""
        )
        formatted_expires_in = (
            (
                _(
                    "Semi-Expires in %d blocks\nExpires %s (in %d blocks)\nDate/time is only an estimate; do not rely on it!"
                )
                % (semi_expires_in, formatted_expires_datetime, expires_in)
            )
            if expires_in is not None
            else ""
        )

        txout = txid + ":%d" % vout

        self._utxo_dict[txout] = utxo

        labels = [
            formatted_name,
            formatted_value,
            formatted_semi_expires_datetime,
            status,
        ]
        utxo_item = [QStandardItem(x) for x in labels]
        self.set_editability(utxo_item)

        utxo_item[self.Columns.NAME].setFont(QFont(MONOSPACE_FONT))
        utxo_item[self.Columns.VALUE].setFont(QFont(MONOSPACE_FONT))

        utxo_item[self.Columns.NAME].setData(txout, Qt.UserRole)
        utxo_item[self.Columns.NAME].setData(name, Qt.UserRole + USER_ROLE_NAME)
        utxo_item[self.Columns.NAME].setData(value, Qt.UserRole + USER_ROLE_VALUE)

        utxo_item[self.Columns.NAME].setToolTip(_("Double-click name to configure"))
        utxo_item[self.Columns.VALUE].setToolTip(_("Double-click name to configure"))
        utxo_item[self.Columns.SEMI_EXPIRES_IN].setToolTip(formatted_expires_in)
        if status_tooltip is not None:
            utxo_item[self.Columns.STATUS].setToolTip(status_tooltip)

        address = utxo.address
        if self.wallet.is_frozen_address(address) or self.wallet.is_frozen_coin(utxo):
            utxo_item[self.Columns.NAME].setBackground(ColorScheme.BLUE.as_color(True))
            if self.wallet.is_frozen_address(address) and self.wallet.is_frozen_coin(
                utxo
            ):
                utxo_item[self.Columns.NAME].setToolTip(
                    _("Address and coin are frozen")
                )
            elif self.wallet.is_frozen_address(address):
                utxo_item[self.Columns.NAME].setToolTip(_("Address is frozen"))
            elif self.wallet.is_frozen_coin(utxo):
                utxo_item[self.Columns.NAME].setToolTip(_("Coin is frozen"))
        self.model().appendRow(utxo_item)

    # TODO: Break out self.selected_in_column argument into its own attribute
    # so that we can subclass it without re-implementing
    # selected_column_0_user_roles
    def selected_column_0_user_roles(self) -> Optional[List[str]]:
        if not self.model():
            return None
        items = self.selected_in_column(self.Columns.NAME)
        if not items:
            return None
        return [x.data(Qt.UserRole) for x in items]

    # TODO: Break out self.selected_in_column argument into its own attribute
    # so that we can subclass it without re-implementing
    # selected_column_0_user_roles
    def selected_column_0_user_role_identifiers(self) -> Optional[List[bytes]]:
        if not self.model():
            return None
        items = self.selected_in_column(self.Columns.NAME)
        if not items:
            return None
        return [x.data(Qt.UserRole + USER_ROLE_NAME) for x in items]

    # TODO: Break out self.selected_in_column argument into its own attribute
    # so that we can subclass it without re-implementing
    # selected_column_0_user_roles
    def selected_column_0_user_role_values(self) -> Optional[List[bytes]]:
        if not self.model():
            return None
        items = self.selected_in_column(self.Columns.NAME)
        if not items:
            return None
        return [x.data(Qt.UserRole + USER_ROLE_VALUE) for x in items]

    # Using Coin Control to choose name inputs doesn't make sense, so disable
    # it.
    def set_spend_list(self, coins: Optional[List[PartialTxInput]]):
        super().set_spend_list(None)

    def create_menu(self, position):
        selected = self.selected_column_0_user_roles()
        if not selected:
            return
        menu = QMenu()

        menu.addAction(_("Renew"), lambda: self.renew_selected_items())
        if len(selected) == 1:
            txid = selected[0].split(":")[0]
            tx = self.wallet.db.transactions.get(txid)
            if tx:
                label = (
                    self.wallet.get_label(txid) or None
                )  # Prefer None if empty (None hides the Description: field in the window)
                menu.addAction(_("Configure"), lambda: self.configure_selected_item())
                menu.addAction(
                    _("Transaction Details"),
                    lambda: self.parent.show_transaction(tx, tx_desc=label),
                )

        # "Copy ..."

        idx = self.indexAt(position)
        col = idx.column()
        if col == self.Columns.NAME:
            selected_data = self.selected_column_0_user_role_identifiers()
            selected_data_type = "identifier"
        elif col == self.Columns.VALUE:
            selected_data = self.selected_column_0_user_role_values()
            selected_data_type = "value"
        else:
            selected_data = None

        if selected_data is not None and len(selected_data) == 1:
            data = selected_data[0]
            # data will be None if this row is a name_new that we haven't
            # queued a name_firstupdate for, so we don't know the identifier or
            # value.
            if data is not None:
                try:
                    copy_ascii = data.decode("ascii")
                    menu.addAction(
                        _("Copy {} as ASCII").format(selected_data_type),
                        lambda: self.parent.app.clipboard().setText(copy_ascii),
                    )
                except UnicodeDecodeError:
                    pass
                copy_hex = bh2u(data)
                menu.addAction(
                    _("Copy {} as hex").format(selected_data_type),
                    lambda: self.parent.app.clipboard().setText(copy_hex),
                )

        menu.exec_(self.viewport().mapToGlobal(position))

    # TODO: We should be able to pass a password to this function, which would
    # be used for all name_update calls.  That way, we wouldn't need to prompt
    # the user per name.
    def renew_selected_items(self):
        selected = self.selected_in_column(0)
        if not selected:
            return

        name_update = self.parent.console.namespace.get("name_update")
        broadcast = self.parent.console.namespace.get("broadcast")
        addtransaction = self.parent.console.namespace.get("addtransaction")

        for item in selected:
            identifier = item.data(Qt.UserRole + USER_ROLE_NAME)

            try:
                # TODO: support non-ASCII encodings
                tx = name_update(identifier.decode("ascii"), wallet=self.wallet)
            except NameUpdatedTooRecentlyError:
                # The name was recently updated, so skip it and don't renew.
                continue
            except (NotEnoughFunds, NoDynamicFeeEstimates) as e:
                self.parent.show_message(str(e))
                return
            except InternalAddressCorruption as e:
                self.parent.show_error(str(e))
                raise
            except BaseException as e:
                traceback.print_exc(file=sys.stdout)
                self.parent.show_message(str(e))
                return

            try:
                broadcast(tx)
            except Exception as e:
                formatted_name = format_name_identifier(identifier)
                self.parent.show_error(
                    _("Error broadcasting renewal for %s: %s")
                    % (formatted_name, str(e))
                )
                continue

            # We add the transaction to the wallet explicitly because
            # otherwise, the wallet will only learn that the transaction's
            # inputs are spent once the ElectrumX server sends us a copy of the
            # transaction, which is several seconds later, which will cause us
            # to double-spend those inputs in subsequent renewals during this
            # loop.
            status = addtransaction(tx)
            if not status:
                formatted_name = format_name_identifier(identifier)
                self.parent.show_error(
                    _("Error adding renewal for %s to wallet") % formatted_name
                )
                continue

    def configure_selected_item(self):
        selected = self.selected_in_column(0)
        if not selected:
            return
        if len(selected) != 1:
            return

        item = selected[0]

        identifier = item.data(Qt.UserRole + USER_ROLE_NAME)
        initial_value = item.data(Qt.UserRole + USER_ROLE_VALUE)

        show_configure_name(identifier, initial_value, self.parent, False)
