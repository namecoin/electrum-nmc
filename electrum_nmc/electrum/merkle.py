# Electrum - Lightweight Bitcoin Client
# Copyright (c) 2012 Thomas Voegtlin
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

from typing import Sequence

from .util import bh2u
from .crypto import sha256d
from .bitcoin import hash_decode, hash_encode
from .transaction import Transaction


class MerkleVerificationFailure(Exception):
    pass


class InnerNodeOfSpvProofIsValidTx(MerkleVerificationFailure):
    pass


def hash_merkle_root(merkle_branch: Sequence[str], tx_hash: str, leaf_pos_in_tree: int):
    """Return calculated merkle root."""
    try:
        h = hash_decode(tx_hash)
        merkle_branch_bytes = [hash_decode(item) for item in merkle_branch]
        leaf_pos_in_tree = int(leaf_pos_in_tree)  # raise if invalid
    except Exception as e:
        raise MerkleVerificationFailure(e)
    if leaf_pos_in_tree < 0:
        raise MerkleVerificationFailure('leaf_pos_in_tree must be non-negative')
    index = leaf_pos_in_tree
    for item in merkle_branch_bytes:
        if len(item) != 32:
            raise MerkleVerificationFailure('all merkle branch items have to 32 bytes long')
        inner_node = (item + h) if (index & 1) else (h + item)
        _raise_if_valid_tx(bh2u(inner_node))
        h = sha256d(inner_node)
        index >>= 1
    if index != 0:
        raise MerkleVerificationFailure('leaf_pos_in_tree too large for branch')
    return hash_encode(h)


def _raise_if_valid_tx(raw_tx: str):
    # If an inner node of the merkle proof is also a valid tx, chances are, this is an attack.
    # https://lists.linuxfoundation.org/pipermail/bitcoin-dev/2018-June/016105.html
    # https://lists.linuxfoundation.org/pipermail/bitcoin-dev/attachments/20180609/9f4f5b1f/attachment-0001.pdf
    # https://bitcoin.stackexchange.com/questions/76121/how-is-the-leaf-node-weakness-in-merkle-trees-exploitable/76122#76122
    tx = Transaction(raw_tx)
    try:
        tx.deserialize()
    except Exception:
        pass
    else:
        raise InnerNodeOfSpvProofIsValidTx()
