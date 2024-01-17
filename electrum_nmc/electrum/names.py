#!/usr/bin/env python
#
# Electrum-NMC - lightweight Namecoin client
# Copyright (C) 2018-2022 Namecoin Developers
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

from enum import Enum
from typing import Dict, NamedTuple, Optional

from . import constants

def split_name_script(decoded):
    # This case happens if a script was malformed and couldn't be decoded by
    # transaction.get_address_from_output_script.
    if decoded is None:
        return {"name_op": None, "address_scriptPubKey": decoded}

    # name_new TxOuts look like:
    # NAME_NEW (commitment) 2DROP (Bitcoin TxOut)
    match = [ OP_NAME_NEW, OPPushDataGeneric, opcodes.OP_2DROP ]
    if match_script_against_template(decoded[:len(match)], match):
        return {"name_op": {"op": OP_NAME_NEW, "commitment": decoded[1][1]}, "address_scriptPubKey": decoded[len(match):]}

    # name_firstupdate TxOuts look like:
    # NAME_FIRSTUPDATE (name) (salt) (value) 2DROP 2DROP (Bitcoin TxOut)
    match = [ OP_NAME_FIRSTUPDATE, OPPushDataGeneric, OPPushDataGeneric, OPPushDataGeneric, opcodes.OP_2DROP, opcodes.OP_2DROP ]
    if match_script_against_template(decoded[:len(match)], match):
        return {"name_op": {"op": OP_NAME_FIRSTUPDATE, "name": decoded[1][1], "salt": decoded[2][1], "value": decoded[3][1]}, "address_scriptPubKey": decoded[len(match):]}

    # name_update TxOuts look like:
    # NAME_UPDATE (name) (value) 2DROP DROP (Bitcoin TxOut)
    match = [ OP_NAME_UPDATE, OPPushDataGeneric, OPPushDataGeneric, opcodes.OP_2DROP, opcodes.OP_DROP ]
    if match_script_against_template(decoded[:len(match)], match):
        return {"name_op": {"op": OP_NAME_UPDATE, "name": decoded[1][1], "value": decoded[2][1]}, "address_scriptPubKey": decoded[len(match):]}

    return {"name_op": None, "address_scriptPubKey": decoded}

def get_name_op_from_output_script(_bytes):
    try:
        decoded = [x for x in script_GetOp(_bytes)]
    except MalformedBitcoinScript:
        decoded = None

    # Extract the name script if one is present.
    return split_name_script(decoded)["name_op"]

def name_op_to_script(name_op) -> str:
    if name_op is None:
        script = ''
    elif name_op["op"] == OP_NAME_NEW:
        validate_new_length(name_op)
        script = '51'                                 # OP_NAME_NEW
        script += push_script(bh2u(name_op["commitment"]))
        script += '6d'                                # OP_2DROP
    elif name_op["op"] == OP_NAME_FIRSTUPDATE:
        validate_firstupdate_length(name_op)
        script = '52'                                 # OP_NAME_FIRSTUPDATE
        script += push_script(bh2u(name_op["name"]))
        script += push_script(bh2u(name_op["salt"]))
        script += push_script(bh2u(name_op["value"]))
        script += '6d'                                # OP_2DROP
        script += '6d'                                # OP_2DROP
    elif name_op["op"] == OP_NAME_UPDATE:
        validate_update_length(name_op)
        script = '53'                                 # OP_NAME_UPDATE
        script += push_script(bh2u(name_op["name"]))
        script += push_script(bh2u(name_op["value"]))
        script += '6d'                                # OP_2DROP
        script += '75'                                # OP_DROP
    else:
        raise BitcoinException('unknown name op: {}'.format(name_op))
    return script

def validate_new_length(name_op):
    validate_commitment_length(name_op["commitment"])

def validate_firstupdate_length(name_op):
    validate_salt_length(name_op["salt"])
    validate_anyupdate_length(name_op)

def validate_update_length(name_op):
    validate_anyupdate_length(name_op)

def validate_anyupdate_length(name_op):
    validate_identifier_length(name_op["name"])
    validate_value_length(name_op["value"])

def validate_commitment_length(commitment: bytes):
    commitment_length_requirement = 20

    commitment_length = len(commitment)
    if commitment_length != commitment_length_requirement:
        raise BitcoinException('commitment length {} is not equal to requirement of {}'.format(commitment_length, commitment_length_requirement))

def validate_salt_length(salt: bytes):
    salt_length_requirement = 20

    salt_length = len(salt)
    if salt_length != salt_length_requirement:
        raise BitcoinException('salt length {} is not equal to requirement of {}'.format(salt_length, salt_length_requirement))

def validate_identifier_length(identifier: bytes):
    identifier_length_limit = 255

    identifier_length = len(identifier)
    if identifier_length > identifier_length_limit:
        raise BitcoinException('identifier length {} exceeds limit of {}'.format(identifier_length, identifier_length_limit))

def validate_value_length(value: bytes):
    value_length_limit = 520

    value_length = len(value)
    if value_length > value_length_limit:
        raise BitcoinException('value length {} exceeds limit of {}'.format(value_length, value_length_limit))

def validate_master_nameserver(domain: str) -> None:
    if domain.endswith('.'):
        relative_domain = domain[:-1]
        if not validators.domain(relative_domain):
            raise ValueError(f'Invalid domain: {domain}')
    
    else:
        if not validators.domain(domain):
            raise ValueError(f'Invalid domain: {domain}')
        
        TLD = tldextract.extract(domain).suffix
        if not TLD:
            raise ValueError(f'Unrecognized TLD which might indicate an error: {domain}')
        
def build_name_new(identifier: bytes, salt: bytes = None, address: str = None, password: str = None, wallet = None):
    validate_identifier_length(identifier)

    if address is not None and wallet is not None:
        salt = wallet.name_salt(identifier, address, password)

    if salt is None:
        salt = os.urandom(20)

    commitment = build_name_commitment(identifier, salt)

    return {"op": OP_NAME_NEW, "commitment": commitment}, salt

def build_name_commitment(identifier: bytes, salt: bytes) -> bytes:
    preimage = salt + identifier
    commitment = hash_160(preimage)

    return commitment

def name_identifier_to_scripthash(identifier: bytes) -> str:
    name_op = {"op": OP_NAME_UPDATE, "name": identifier, "value": bytes([])}
    script = name_op_to_script(name_op)
    script += '6a' # OP_RETURN

    return script_to_scripthash(script)


class Encoding(Enum):
    ASCII = "ascii"
    UTF8 = "utf8"
    HEX = "hex"


def name_to_str(data: bytes, enc: Encoding) -> str:
    if enc == Encoding.ASCII:
        # Python checks for >= 0x80 here
        result = data.decode("ascii")
        for c in result:
            if ord(c) < 0x20:
                raise UnicodeDecodeError('ascii', data, result.index(c), result.rindex(c)+1, 'Control characters forbidden')
        return result
    if enc == Encoding.UTF8:
        return data.decode("utf-8")
    if enc == Encoding.HEX:
        return bh2u(data)


def name_from_str(data_str: str, enc: Encoding) -> bytes:
    if enc == Encoding.ASCII:
        for c in data_str:
            if ord(c) < 0x20:
                raise UnicodeEncodeError('ascii', data_str, data_str.index(c), data_str.rindex(c)+1, 'Control characters forbidden')
        # Python checks for >= 0x80 here
        return data_str.encode("ascii")
    if enc == Encoding.UTF8:
        return data_str.encode("utf-8")
    if enc == Encoding.HEX:
        try:
            return bfh(data_str)
        except ValueError as e:
            raise UnicodeEncodeError('hex', data_str, 0, len(data_str), str(e))


def identifier_to_namespace(identifier_bytes: bytes) -> Optional[str]:
    try:
        identifier = identifier_bytes.decode("ascii")
    except UnicodeDecodeError:
        return None

    try:
        namespace, label = identifier.split("/", 1)
    except ValueError:
        return None

    if namespace == "d":
        if len(label) < 1:
            return None

        # Source: https://github.com/namecoin/proposals/blob/master/ifa-0001.md#keys
        if len(label) > 63:
            return None

        # Source: https://github.com/namecoin/proposals/blob/master/ifa-0001.md#keys
        label_regex = r"^(xn--)?[a-z0-9]+(-[a-z0-9]+)*$"
        label_match = re.match(label_regex, label)
        if label_match is None:
            return None

        # Reject digits-only labels
        number_regex = r"^[0-9]+$"
        number_match = re.match(number_regex, label)
        if number_match is not None:
            return None

        return namespace

    if namespace == "id":
        if len(label) < 1:
            return None

        # Max id/ identifier length is 255 chars according to wiki spec.  But we
        # don't need to check for this, because that's also the max length of an
        # identifier under the Namecoin consensus rules.

        # Same as d/ regex but without IDN prefix.
        # TODO: this doesn't exactly match the https://wiki.namecoin.org spec.
        label_regex = r"^[a-z0-9]+(-[a-z0-9]+)*$"
        label_match = re.match(label_regex, label)
        if label_match is None:
            return None

        return namespace

    return namespace


class FormattedNameIdentifier(NamedTuple):
    category: str
    specifics: str


def format_name_identifier(identifier_bytes: bytes) -> str:
    split = format_name_identifier_split(identifier_bytes)

    return split.category + " " + split.specifics


def format_name_identifier_split(identifier_bytes: bytes) -> FormattedNameIdentifier:
    try:
        identifier = identifier_bytes.decode("ascii")
    except UnicodeDecodeError:
        return format_name_identifier_unknown_hex(identifier_bytes)

    namespace = identifier_to_namespace(identifier_bytes)

    if namespace == "d":
        return format_name_identifier_domain(identifier)

    if namespace == "id":
        return format_name_identifier_identity(identifier)

    return format_name_identifier_unknown(identifier)


def format_name_identifier_domain(identifier: str) -> FormattedNameIdentifier:
    label = identifier[len("d/"):]

    return FormattedNameIdentifier("Domain", label + ".bit")


def format_name_identifier_identity(identifier: str) -> FormattedNameIdentifier:
    label = identifier[len("id/"):]

    return FormattedNameIdentifier("Identity", label)


def format_name_identifier_unknown(identifier: str) -> FormattedNameIdentifier:
    # Check for non-printable characters, and print ASCII if none are found.
    if identifier.isprintable():
        return FormattedNameIdentifier("Non-standard name", f"'{identifier}'")

    return format_name_identifier_unknown_hex(identifier.encode("ascii"))


def format_name_identifier_unknown_hex(identifier_bytes: bytes) -> FormattedNameIdentifier:
    return FormattedNameIdentifier("Non-standard name", "0x" + bh2u(identifier_bytes))


def format_name_value(value_bytes: bytes) -> str:
    try:
        value = value_bytes.decode("ascii")
    except UnicodeDecodeError:
        return format_name_value_hex(value_bytes)

    if not value.isprintable():
        return format_name_value_hex(value_bytes)

    return f"'{value}'"


def format_name_value_hex(value_bytes: bytes) -> str:
    return "0x" + bh2u(value_bytes)


def format_name_op(name_op) -> str:
    if name_op is None:
        return ''
    if "commitment" in name_op:
        formatted_commitment = "Commitment = " + bh2u(name_op["commitment"])
    if "salt" in name_op:
        formatted_salt = "Salt = " + bh2u(name_op["salt"])
    if "name" in name_op:
        formatted_name = "Name = " + format_name_identifier(name_op["name"])
    if "value" in name_op:
        formatted_value = "Data = " + format_name_value(name_op["value"])

    if name_op["op"] == OP_NAME_NEW:
        return "\tPre-Registration\n\t\t" + formatted_commitment
    if name_op["op"] == OP_NAME_FIRSTUPDATE:
        return "\tRegistration\n\t\t" + formatted_name + "\n\t\t" + formatted_salt + "\n\t\t" + formatted_value
    if name_op["op"] == OP_NAME_UPDATE:
        return "\tUpdate\n\t\t" + formatted_name + "\n\t\t" + formatted_value


def name_op_to_json(name_op: Dict) -> Dict[str, str]:
    result = deepcopy(name_op)

    op_str = {
        OP_NAME_NEW: "name_new",
        OP_NAME_FIRSTUPDATE: "name_firstupdate",
        OP_NAME_UPDATE: "name_update",
    }

    result["op"] = op_str[result["op"]]

    if "commitment" in result:
        result["commitment"] = result["commitment"].hex()
    if "salt" in result:
        result["salt"] = result["salt"].hex()
    if "name" in result:
        result["name"] = result["name"].hex()
        result["name_encoding"] = "hex"
    if "value" in result:
        result["value"] = result["value"].hex()
        result["value_encoding"] = "hex"

    return result


def get_default_name_tx_label(wallet, tx) -> Optional[str]:
    for idx, o in enumerate(tx.outputs()):
        name_op = o.name_op
        if name_op is not None:
            # TODO: Handle multiple atomic name ops.
            name_input_is_mine, name_output_is_mine, name_value_is_unchanged = get_wallet_name_delta(wallet, tx)
            if not name_input_is_mine and not name_output_is_mine:
                return None
            if name_input_is_mine and not name_output_is_mine:
                return "Transfer (Outgoing): " + format_name_identifier(name_op["name"])
            if not name_input_is_mine and name_output_is_mine:
                # A name_new transaction isn't expected to have a name input,
                # so we don't consider it a transfer.
                if name_op["op"] != OP_NAME_NEW:
                    return "Transfer (Incoming): " + format_name_identifier(name_op["name"])
            if name_op["op"] == OP_NAME_NEW:
                # Get the address where the NAME_NEW was sent to
                addr = o.address
                # Look for other transactions for this address, which might
                # include the NAME_FIRSTUPDATE
                addr_history = wallet.get_address_history(addr)
                for addr_txid, addr_height in addr_history:
                    # Examine a candidate tx that might be the NAME_FIRSTUPDATE
                    addr_tx = wallet.db.transactions.get(addr_txid)
                    # Look at all the candidate's inputs to make sure it's
                    # actually spending the NAME_NEW
                    for addr_tx_input in addr_tx.inputs():
                        if addr_tx_input.prevout.txid.hex() == tx.txid():
                            if addr_tx_input.prevout.out_idx == idx:
                                # We've confirmed that it spends the NAME_NEW.
                                # Look at the outputs to find the
                                # NAME_FIRSTUPDATE.
                                for addr_tx_output in addr_tx.outputs():
                                    if addr_tx_output.name_op is not None:
                                        # We've found a name output; now we
                                        # check for an identifier.
                                        if 'name' in addr_tx_output.name_op:
                                            return "Pre-Registration: " + format_name_identifier(addr_tx_output.name_op['name'])

                # Look for queued transactions that spend the NAME_NEW
                _, addr_tx_output = get_queued_firstupdate_from_new(wallet, tx.txid(), idx)
                if addr_tx_output is not None:
                    return "Pre-Registration: " + format_name_identifier(addr_tx_output.name_op['name'])

                # A name_new transaction doesn't have a visible 'name' field,
                # so there's nothing to format if we can't find the name
                # elsewhere in the wallet.
                return "Pre-Registration"
            if name_op["op"] == OP_NAME_FIRSTUPDATE:
                return "Registration: " + format_name_identifier(name_op["name"])
            if name_op["op"] == OP_NAME_UPDATE:
                if name_value_is_unchanged:
                    return "Renew: " + format_name_identifier(name_op["name"])
                else:
                    return "Update: " + format_name_identifier(name_op["name"])
    return None


def get_queued_firstupdate_from_new(wallet, txid, idx):
    # Look for queued transactions that spend the NAME_NEW
    for addr_txid in wallet.db.queued_transactions:
        addr_tx_queue_item = wallet.db.queued_transactions[addr_txid]
        # Check whether the queued transaction is contingent on the NAME_NEW transaction
        if addr_tx_queue_item['sendWhen']['txid'] == txid:
            addr_tx = Transaction(addr_tx_queue_item['tx'])
            # Look at all the candidate's inputs to make sure it's
            # actually spending the NAME_NEW
            for addr_tx_input in addr_tx.inputs():
                if addr_tx_input.prevout.txid.hex() == txid:
                    if addr_tx_input.prevout.out_idx == idx:
                        # We've confirmed that it spends the NAME_NEW.
                        # Look at the outputs to find the
                        # NAME_FIRSTUPDATE.
                        for addr_tx_output in addr_tx.outputs():
                            if addr_tx_output.name_op is not None:
                                # We've found a name output; now we
                                # check for an identifier.
                                if 'name' in addr_tx_output.name_op:
                                    return addr_tx_queue_item, addr_tx_output
    return None, None


def get_wallet_name_delta(wallet, tx, domain=None):
    # get domain
    if domain is None:
        domain = wallet.get_addresses()
    domain = set(domain)

    name_input_is_mine = False
    name_output_is_mine = False

    name_input_value = None
    name_output_value = None

    def nameop_is_mine(inout):
        if inout.address is None:
            return False
        if not wallet.is_mine(inout.address):
            return False
        if inout.address not in domain:
            return False
        if inout.name_op is None:
            return False
        return True

    tx = PartialTransaction.from_tx(tx)
    for txin in tx.inputs():
        wallet.add_input_info(txin)
        if nameop_is_mine(txin):
            name_input_is_mine = True
            if 'value' in txin.name_op:
                name_input_value = txin.name_op['value']
    for o in tx.outputs():
        if nameop_is_mine(o):
            name_output_is_mine = True
            if 'value' in o.name_op:
                name_output_value = o.name_op['value']

    name_value_is_unchanged = name_input_value == name_output_value

    return name_input_is_mine, name_output_is_mine, name_value_is_unchanged


def get_wallet_name_count(wallet, network):
    confirmed_count = 0
    pending_count = 0

    utxos = wallet.get_utxos()
    for x in utxos:
        txid = x.prevout.txid
        vout = x.prevout.out_idx
        name_op = x.name_op
        if name_op is None:
            continue
        height = x.block_height
        chain_height = network.blockchain().height()
        expires_in = name_expires_in(height, chain_height)
        if expires_in is None:
            # Transaction isn't mined yet
            if name_op['op'] in [OP_NAME_NEW, OP_NAME_FIRSTUPDATE]:
                # Registration is pending
                pending_count += 1
                continue
            else:
                # name_update is pending
                # TODO: we shouldn't consider it confirmed if it's an incoming
                # or outgoing transfer.
                confirmed_count += 1
                continue
        if expires_in <= 0:
            # Expired
            continue
        if 'name' in name_op:
            # name_anyupdate is mined (not expired)
            confirmed_count += 1
            continue
        else:
            # name_new is mined
            pending_count += 1
            continue
    return confirmed_count, pending_count

def blocks_remaining_until_confirmations(name_height: Optional[int], chain_height, confirmations) -> Optional[int]:
    if name_height is None:
        return None

    if name_height <= 0:
        return None

    # If name_height == chain_height, then it has 1 confirmation, so we
    # subtract 1 to offset it.
    return name_height - chain_height + confirmations - 1

def name_new_mature_in(name_height: Optional[int], chain_height) -> Optional[int]:
    # name_new matures at 12 confirmations.
    return blocks_remaining_until_confirmations(name_height, chain_height, 12)

def name_expires_in(name_height: Optional[int], chain_height) -> Optional[int]:
    # Names expire at 36001 confirmations.
    return blocks_remaining_until_confirmations(name_height, chain_height, constants.net.NAME_EXPIRATION + 1)

def name_semi_expires_in(name_height: Optional[int], chain_height) -> Optional[int]:
    return blocks_remaining_until_confirmations(name_height, chain_height, constants.net.NAME_SEMI_EXPIRATION + 1)

def name_expiration_datetime_estimate(name_height: Optional[int], chain, blocks_func = name_expires_in):
    chain_height = chain.header_at_tip()['block_height']

    expiration_blocks = blocks_func(name_height, chain_height)

    if expiration_blocks is None:
        return None, None

    # Try getting the exact timestamp.  This will fail if the header isn't
    # available or is in the future.
    expiration_height = chain_height + expiration_blocks
    expiration_header = chain.read_header(expiration_height)
    if expiration_header is not None:
        expiration_datetime = datetime.fromtimestamp(expiration_header['timestamp'])
        return expiration_blocks, expiration_datetime

    # Exact timestamp isn't available, so estimate it via 10-minute block
    # interval and chain tip timestamp.
    block_timedelta = timedelta(minutes=10)
    expiration_timedelta = expiration_blocks * block_timedelta
    chain_datetime = datetime.fromtimestamp(chain.header_at_tip()['timestamp'])
    return expiration_blocks, chain_datetime + expiration_timedelta

def get_domain_records(domain, value):
    if type(value) == bytes:
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return [], value

    if type(value) == str:
        if value == "":
            value = "{}"

        try:
            value = json.loads(value)
        except json.decoder.JSONDecodeError:
            return [], value

    if type(value) != dict:
        return [], value

    records = []

    new_records, value = get_domain_records_address(domain, value)
    records.extend(new_records)

    if "alias" in value:
        new_records, value["alias"] = get_domain_records_cname(domain, value["alias"])
        records.extend(new_records)
        if value["alias"] is None:
            del value["alias"]

    if "ns" in value:
        new_records, value["ns"] = get_domain_records_ns(domain, value["ns"])
        records.extend(new_records)
        if value["ns"] == []:
            del value["ns"]

    if "ds" in value:
        new_records, value["ds"] = get_domain_records_ds(domain, value["ds"])
        records.extend(new_records)
        if value["ds"] == []:
            del value["ds"]

    if "tls" in value:
        new_records, value["tls"] = get_domain_records_tls(domain, value["tls"])
        records.extend(new_records)
        if value["tls"] == []:
            del value["tls"]

    if "sshfp" in value:
        new_records, value["sshfp"] = get_domain_records_sshfp(domain, value["sshfp"])
        records.extend(new_records)
        if value["sshfp"] == []:
            del value["sshfp"]

    if "txt" in value:
        new_records, value["txt"] = get_domain_records_txt(domain, value["txt"])
        records.extend(new_records)
        if value["txt"] == []:
            del value["txt"]

    if "srv" in value:
        new_records, value["srv"] = get_domain_records_srv(domain, value["srv"])
        records.extend(new_records)
        if value["srv"] == []:
            del value["srv"]

    if "import" in value:
        new_records, value["import"] = get_domain_records_import(domain, value["import"])
        records.extend(new_records)
        if value["import"] == []:
            del value["import"]

    if "map" in value:
        new_records, value["map"] = get_domain_records_map(domain, value["map"])
        records.extend(new_records)
        if value["map"] == {}:
            del value["map"]

    return records, value

def get_domain_records_address(domain, value):
    records = []

    if "ip" in value:
        new_records, value["ip"] = get_domain_records_address_ip4(domain, value["ip"])
        records.extend(new_records)
        if value["ip"] == []:
            del value["ip"]

    if "ip6" in value:
        new_records, value["ip6"] = get_domain_records_address_ip6(domain, value["ip6"])
        records.extend(new_records)
        if value["ip6"] == []:
            del value["ip6"]

    if "tor" in value:
        new_records, value["tor"] = get_domain_records_address_tor(domain, value["tor"])
        records.extend(new_records)
        if value["tor"] == []:
            del value["tor"]

    if "i2p" in value:
        new_records, value["i2p"] = get_domain_records_address_i2p(domain, value["i2p"])
        records.extend(new_records)
        if value["i2p"] == []:
            del value["i2p"]

    if "freenet" in value:
        new_records, value["freenet"] = get_domain_records_address_freenet(domain, value["freenet"])
        records.extend(new_records)
        if value["freenet"] is None:
            del value["freenet"]

    if "zeronet" in value:
        new_records, value["zeronet"] = get_domain_records_address_zeronet(domain, value["zeronet"])
        records.extend(new_records)
        if value["zeronet"] is None:
            del value["zeronet"]

    return records, value

def get_domain_records_address_ip4(domain, value):
    # Convert string to array (only 1 A record exists)
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_address_ip4_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_address_ip4_single(domain, value):
    # Must be string
    if type(value) != str:
        return None, value

    return [domain, "address", ["ip4", value]], None

def get_domain_records_address_ip6(domain, value):
    # Convert string to array (only 1 AAAA record exists)
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_address_ip6_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_address_ip6_single(domain, value):
    # Must be string
    if type(value) != str:
        return None, value

    return [domain, "address", ["ip6", value]], None

def get_domain_records_address_tor(domain, value):
    # Convert string to array (only 1 Tor record exists)
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_address_tor_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_address_tor_single(domain, value):
    # Must be string
    if type(value) != str:
        return None, value

    return [domain, "address", ["tor", value]], None

def get_domain_records_address_i2p(domain, value):
    # Convert string to array (only 1 I2P record exists)
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_address_i2p_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_address_i2p_single(domain, value):
    # Must be string
    if type(value) != str:
        return None, value

    return [domain, "address", ["i2p", value]], None

def get_domain_records_address_freenet(domain, value):
    records = []
    remaining = None

    # Must be string
    if type(value) != str:
        return [], value

    records.append([domain, "address", ["freenet", value]])

    return records, remaining

def get_domain_records_address_zeronet(domain, value):
    records = []
    remaining = None

    # Parse the standards-compliant ZeroNet format
    if type(value) == str:
        records.append([domain, "address", ["zeronet", value]])

    # Parse the old-style dict ZeroNet format
    if type(value) == dict:
        for label in value:
            # Make sure the ZeroNet value is a string, bail if it's not
            if type(value[label]) != str:
                return [], value

            # Special-case for empty ZeroNet key
            if label == "":
                single_domain = domain
            else:
                single_domain = label + "." + domain

            records.append([single_domain, "address", ["zeronet", value[label]]])

    return records, remaining

def get_domain_records_cname(domain, value):
    records = []
    remaining = None

    # Must be string
    if type(value) != str:
        return [], value

    records.append([domain, "cname", value])

    return records, remaining

def get_domain_records_ns(domain, value):
    # Convert string to array (only 1 NS record exists)
    if type(value) == str:
        value = [value]
    
    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_ns_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_ns_single(domain, value):
    # Must be string
    if type(value) != str:
        return None, value

    return [domain, "ns", value], None

def get_domain_records_ds(domain, value):
    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_ds_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_ds_single(domain, value):
    # Must be array
    if type(value) != list:
        return None, value

    # Must be length 4
    if len(value) != 4:
        return None, value

    # Check value types
    if type(value[0]) != int or type(value[1]) != int or type(value[2]) != int or type(value[3]) != str:
        return None, value

    return [domain, "ds", value], None

def get_domain_records_tls(domain, value):
    # Handle TLS subdomain; domain must be eTLD+2
    try:
        wildcard, sld, tld = domain.split(".")
        domain = sld + "." + tld
    except ValueError:
        return [], value

    # Must be "*" subdomain of eTLD+1
    if wildcard != "*":
        return [], value

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_tls_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_tls_single(domain, value):
    # Convert array to dict (default DANE format)
    if type(value) == list:
        value = {"dane": value}

    # Must be dict
    if type(value) != dict:
        return None, value

    # Technically a TLS object can have both Dehydrated and DANE versions at once.
    # This is unusual and we don't try to handle this.
    if len(value) != 1:
        return None, value

    # Check format
    if "dane" not in value:
        return None, value

    cert = value["dane"]
    if not isinstance(cert, list):
        return None, value
    if len(cert) != 4:
        return None, value
    if cert[:3] != [2, 1, 0]:
        return None, value

    pubkey = cert[3]
    if not isinstance(pubkey, str):
        return None, value

    return [domain, "tls", pubkey], None

def get_domain_records_sshfp(domain, value):
    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_sshfp_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_sshfp_single(domain, value):
    # Must be array
    if type(value) != list:
        return None, value

    # Must be length 3
    if len(value) != 3:
        return None, value

    # Check value types
    if type(value[0]) != int or type(value[1]) != int or type(value[2]) != str:
        return None, value

    return [domain, "sshfp", value], None

def get_domain_records_txt(domain, value):
    # Process Tor specially
    if domain.startswith("_tor."):
        domain = domain[len("_tor."):]
        return get_domain_records_address_tor(domain, value)

    # Convert string to array (only 1 TXT record exists)
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_txt_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_txt_single(domain, value):
    # Must be string
    if type(value) != str:
        return None, value

    # TODO: Handle TXT records that are an array.

    return [domain, "txt", value], None

def get_domain_records_srv(domain, value):
    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_srv_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_srv_single(domain, value):
    # Must be array
    if type(value) != list:
        return None, value

    # Must be length 4
    if len(value) != 4:
        return None, value

    # Check value types
    if type(value[0]) != int or type(value[1]) != int or type(value[2]) != int or type(value[3]) != str:
        return None, value

    return [domain, "srv", value], None

def get_domain_records_import(domain, value):
    # Convert string to array (only 1 IMPORT record exists)
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return [], value

    # Parse each array item
    records = []
    remaining = []
    for raw_address in value:
        single_record, single_remaining = get_domain_records_import_single(domain, raw_address)
        if single_record is not None:
            records.append(single_record)
        if single_remaining is not None:
            remaining.append(single_remaining)

    return records, remaining

def get_domain_records_import_single(domain, value):
    # Convert string to array
    if type(value) == str:
        value = [value]

    # Must be array
    if type(value) != list:
        return None, value

    # Name must be present
    if len(value) < 1:
        return None, value

    # Name must be a string
    if type(value[0]) != str:
        return None, value

    # Don't process IMPORT records with unknown fields
    if len(value) > 2:
        return None, value

    # Add Subdomain Selector if missing
    if len(value) < 2:
        value.append("")

    return [domain, "import", value], None

def get_domain_records_map(domain, value):
    # Must be dict
    if type(value) != dict:
        return [], value

    # Parse each dict item
    records = []
    remaining = {}
    for subdomain in value:
        # Special form where map key is empty
        if subdomain == "":
            # This special form is a security hazard and should be avoided.  We
            # therefore don't parse it.  If you want to parse it, uncomment the
            # next line, and comment out the "continue".
            #single_domain = domain
            continue
        else:
            single_domain = subdomain + "." + domain

        # Special form where a map value is a string
        single_value = value[subdomain]
        if type(single_value) == str:
            single_value = {"ip": single_value}

        new_records, remaining[subdomain] = get_domain_records(single_domain, single_value)

        records.extend(new_records)
        if remaining[subdomain] == {}:
            del remaining[subdomain]

    return records, remaining

def add_domain_record(base_domain, value, record):
    domain, record_type, data = record

    # Handle Tor records specially
    if record_type == "address" and data[0] == "tor":
        domain = "_tor." + domain
        record_type = "txt"
        data = data[1]

    # Handle TLS record specially to prepend wildcard subdomain
    if record_type == "tls":
        domain = "*." + domain

    if not domain.endswith(base_domain):
        raise Exception("Base domain mismatch")

    if domain == base_domain:
        map_labels = []
    else:
        subdomain = domain[:-len("." + base_domain)]
        map_labels = subdomain.split(".")[::-1]

    add_domain_record_map(value, map_labels)

    # Traverse the "map" field until we arrive at the subdomain we want
    subdomain_value = value
    for label in map_labels:
        subdomain_value = subdomain_value["map"][label]

    if record_type == "address":
        add_domain_record_address(subdomain_value, data)
    elif record_type == "cname":
        add_domain_record_cname(subdomain_value, data)
    elif record_type == "ns":
        add_domain_record_ns(subdomain_value, data)
    elif record_type == "ds":
        add_domain_record_ds(subdomain_value, data)
    elif record_type == "tls":
        add_domain_record_tls(subdomain_value, data)
    elif record_type == "sshfp":
        add_domain_record_sshfp(subdomain_value, data)
    elif record_type == "txt":
        add_domain_record_txt(subdomain_value, data)
    elif record_type == "srv":
        add_domain_record_srv(subdomain_value, data)
    elif record_type == "import":
        add_domain_record_import(subdomain_value, data)

def add_domain_record_map(value, map_labels):
    if len(map_labels) == 0:
        return

    # Make sure the map field exists
    if "map" not in value:
        value["map"] = {}

    # Make sure the subdomain exists
    if map_labels[0] not in value["map"]:
        value["map"][map_labels[0]] = {}

    # Move onto the next map label
    add_domain_record_map(value["map"][map_labels[0]], map_labels[1:])

def add_domain_record_address(value, data):
    address_type, address_data = data
    if address_type == "ip4":
        add_domain_record_address_ip4(value, address_data)
    elif address_type == "ip6":
        add_domain_record_address_ip6(value, address_data)
    elif address_type == "i2p":
        add_domain_record_address_i2p(value, address_data)
    elif address_type == "freenet":
        add_domain_record_address_freenet(value, address_data)
    elif address_type == "zeronet":
        add_domain_record_address_zeronet(value, address_data)
    else:
        raise Exception("Unknown address type")

def add_domain_record_address_ip4(value, data):
    # Make sure the field exists
    if "ip" not in value:
        value["ip"] = []

    # Make sure the field is an array
    if type(value["ip"]) == str:
        value["ip"] = [value["ip"]]

    # Add the record
    value["ip"].append(data)

    # Minimize to string form if possible
    if len(value["ip"]) == 1:
        value["ip"] = value["ip"][0]

def add_domain_record_address_ip6(value, data):
    # Make sure the field exists
    if "ip6" not in value:
        value["ip6"] = []

    # Make sure the field is an array
    if type(value["ip6"]) == str:
        value["ip6"] = [value["ip6"]]

    # Add the record
    value["ip6"].append(data)

    # Minimize to string form if possible
    if len(value["ip6"]) == 1:
        value["ip6"] = value["ip6"][0]

def add_domain_record_address_i2p(value, data):
    # Make sure the field exists
    if "i2p" not in value:
        value["i2p"] = []

    # Make sure the field is an array
    if type(value["i2p"]) == str:
        value["i2p"] = [value["i2p"]]

    # Add the record
    value["i2p"].append(data)

    # Minimize to string form if possible
    if len(value["i2p"]) == 1:
        value["i2p"] = value["i2p"][0]

def add_domain_record_address_freenet(value, data):
    # Make sure the field doesn't already exist
    if "freenet" in value:
        raise Exception("Multiple Freenet records for one domain")

    # Add the record
    value["freenet"] = data

def add_domain_record_address_zeronet(value, data):
    # Make sure the field doesn't already exist
    if "zeronet" in value:
        raise Exception("Multiple ZeroNet records for one domain")

    # Add the record
    value["zeronet"] = data

def add_domain_record_cname(value, data):
    # Make sure the field doesn't already exist
    if "alias" in value:
        raise Exception("Multiple CNAME records for one domain")

    # Add the record
    value["alias"] = data

def add_domain_record_ns(value, data):
    # Make sure the field exists
    if "ns" not in value:
        value["ns"] = []

    # Make sure the field is an array
    if type(value["ns"]) == str:
        value["ns"] = [value["ns"]]

    # Add the record
    value["ns"].append(data)

    # Minimize to string form if possible
    if len(value["ns"]) == 1:
        value["ns"] = value["ns"][0]

def add_domain_record_ds(value, data):
    # Make sure the field exists
    if "ds" not in value:
        value["ds"] = []

    # Add the record
    value["ds"].append(data)

def add_domain_record_tls(value, data):
    # Make sure the field exists
    if "tls" not in value:
        value["tls"] = []

    # Fill in hardcoded DANE params
    data = [2, 1, 0, data]

    # Add the record
    value["tls"].append(data)

def add_domain_record_sshfp(value, data):
    # Make sure the field exists
    if "sshfp" not in value:
        value["sshfp"] = []

    # Add the record
    value["sshfp"].append(data)

def add_domain_record_txt(value, data):
    # Make sure the field exists
    if "txt" not in value:
        value["txt"] = []

    # Make sure the field is an array
    if type(value["txt"]) == str:
        value["txt"] = [value["txt"]]

    # Add the record
    value["txt"].append(data)

    # Minimize to string form if possible
    if len(value["txt"]) == 1:
        value["txt"] = value["txt"][0]

def add_domain_record_srv(value, data):
    # Make sure the field exists
    if "srv" not in value:
        value["srv"] = []

    # Add the record
    value["srv"].append(data)

def add_domain_record_import(value, data):
    # Make sure the field exists
    if "import" not in value:
        value["import"] = []

    # Make sure the field is an array
    if type(value["import"]) == str:
        value["import"] = [value["import"]]

    # Minimize empty Subdomain Selector if possible
    if type(data) == list and len(data) == 2 and data[1] == "":
        data = data[0]

    # Minimize missing Subdomain Selector if possible
    if type(data) == list and len(data) == 1:
        data = data[0]

    # Add the record
    value["import"].append(data)

    # Minimize to string form if possible
    if len(value["import"]) == 1 and type(value["import"][0]) == str:
        value["import"] = value["import"][0]


import binascii
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
import re
import tldextract
import validators

from .bitcoin import push_script, script_to_scripthash
from .crypto import hash_160
from .transaction import MalformedBitcoinScript, match_script_against_template, opcodes, OPPushDataGeneric, PartialTransaction, script_GetOp, Transaction
from .util import bh2u, bfh, BitcoinException

OP_NAME_NEW = opcodes.OP_1
OP_NAME_FIRSTUPDATE = opcodes.OP_2
OP_NAME_UPDATE = opcodes.OP_3

