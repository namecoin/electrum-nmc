#!/usr/bin/env python
#
# Electrum-NMC - lightweight Namecoin client
# Copyright (C) 2018 Namecoin Developers
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

def split_name_script(decoded):
    # name_new TxOuts look like:
    # NAME_NEW (hash) 2DROP (Bitcoin TxOut)
    match = [ OP_NAME_NEW, opcodes.OP_PUSHDATA4, opcodes.OP_2DROP ]
    if match_decoded(decoded[:len(match)], match):
        return {"name_op": {"op": OP_NAME_NEW, "hash": decoded[1][1]}, "address_scriptPubKey": decoded[len(match):]}

    # name_firstupdate TxOuts look like:
    # NAME_FIRSTUPDATE (name) (rand) (value) 2DROP 2DROP (Bitcoin TxOut)
    match = [ OP_NAME_FIRSTUPDATE, opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4, opcodes.OP_2DROP, opcodes.OP_2DROP ]
    if match_decoded(decoded[:len(match)], match):
        return {"name_op": {"op": OP_NAME_FIRSTUPDATE, "name": decoded[1][1], "rand": decoded[2][1], "value": decoded[3][1]}, "address_scriptPubKey": decoded[len(match):]}

    # name_update TxOuts look like:
    # NAME_UPDATE (name) (value) 2DROP DROP (Bitcoin TxOut)
    match = [ OP_NAME_UPDATE, opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4, opcodes.OP_2DROP, opcodes.OP_DROP ]
    if match_decoded(decoded[:len(match)], match):
        return {"name_op": {"op": OP_NAME_UPDATE, "name": decoded[1][1], "value": decoded[2][1]}, "address_scriptPubKey": decoded[len(match):]}

    return {"name_op": None, "address_scriptPubKey": decoded}

def get_name_op_from_output_script(_bytes):
    decoded = [x for x in script_GetOp(_bytes)]

    # Extract the name script if one is present.
    return split_name_script(decoded)["name_op"]

def name_op_to_script(name_op):
    if name_op is None:
        script = ''
    elif name_op["op"] == OP_NAME_NEW:
        script = '51'                                 # OP_NAME_NEW
        script += push_script(bh2u(name_op["hash"]))
        script += '6d'                                # OP_2DROP
    elif name_op["op"] == OP_NAME_FIRSTUPDATE:
        script = '52'                                 # OP_NAME_FIRSTUPDATE
        script += push_script(bh2u(name_op["name"]))
        script += push_script(bh2u(name_op["rand"]))
        script += push_script(bh2u(name_op["value"]))
        script += '6d'                                # OP_2DROP
        script += '6d'                                # OP_2DROP
    elif name_op["op"] == OP_NAME_UPDATE:
        script = '53'                                 # OP_NAME_UPDATE
        script += push_script(bh2u(name_op["name"]))
        script += push_script(bh2u(name_op["value"]))
        script += '6d'                                # OP_2DROP
        script += '75'                                # OP_DROP
    else:
        raise BitcoinException('unknown name op: {}'.format(name_op))
    return script


def format_name_op(name_op):
    if name_op is None:
        return ''
    if "hash" in name_op:
        formatted_hash = "Commitment = " + bh2u(name_op["hash"])
    if "rand" in name_op:
        formatted_rand = "Salt = " + bh2u(name_op["rand"])
    if "name" in name_op:
        formatted_name = "Name = Hex " + bh2u(name_op["name"])
    if "value" in name_op:
        formatted_value = "Data = Hex " + bh2u(name_op["value"])

    if name_op["op"] == OP_NAME_NEW:
        return "\tName Pre-Registration\n\t\t" + formatted_hash
    if name_op["op"] == OP_NAME_FIRSTUPDATE:
        return "\tName Registration\n\t\t" + formatted_name + "\n\t\t" + formatted_rand + "\n\t\t" + formatted_value
    if name_op["op"] == OP_NAME_UPDATE:
        return "\tName Update\n\t\t" + formatted_name + "\n\t\t" + formatted_value


def get_default_name_tx_label(tx):
    for addr, v, name_op in tx.get_outputs():
        if name_op is not None:
            # TODO: Handle multiple atomic name ops.
            # TODO: Include "name" field.
            if name_op["op"] == OP_NAME_NEW:
                return "Name Pre-Registration"
            if name_op["op"] == OP_NAME_FIRSTUPDATE:
                return "Name Registration"
            if name_op["op"] == OP_NAME_UPDATE:
                return "Name Update"
    return None


from .bitcoin import push_script
from .transaction import match_decoded, opcodes, script_GetOp
from .util import bh2u

OP_NAME_NEW = opcodes.OP_1
OP_NAME_FIRSTUPDATE = opcodes.OP_2
OP_NAME_UPDATE = opcodes.OP_3

