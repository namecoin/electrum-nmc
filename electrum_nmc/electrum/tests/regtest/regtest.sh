#!/usr/bin/env bash
export HOME=~
set -eu

# alice -> bob -> carol

alice="./run_electrum_nmc --regtest -D /tmp/alice"
bob="./run_electrum_nmc --regtest -D /tmp/bob"
carol="./run_electrum_nmc --regtest -D /tmp/carol"

bitcoin_cli="namecoin-cli -rpcuser=doggman -rpcpassword=donkey -rpcport=18554 -regtest"

function new_blocks()
{
    $bitcoin_cli generatetoaddress $1 $($bitcoin_cli getnewaddress) > /dev/null
}

function wait_for_balance()
{
    msg="wait until $1's balance reaches $2"
    cmd="./run_electrum_nmc --regtest -D /tmp/$1"
    while balance=$($cmd getbalance | jq '[.confirmed, .unconfirmed] | to_entries | map(select(.value != null).value) | map(tonumber) | add ') && (( $(echo "$balance < $2" | bc -l) )); do
        sleep 1
	msg="$msg."
	printf "$msg\r"
    done
    printf "\n"
}

function wait_until_channel_open()
{
    msg="wait until $1 sees channel open"
    cmd="./run_electrum_nmc --regtest -D /tmp/$1"
    while channel_state=$($cmd list_channels | jq '.[0] | .state' | tr -d '"') && [ $channel_state != "OPEN" ]; do
        sleep 1
	msg="$msg."
	printf "$msg\r"
    done
    printf "\n"
}

function wait_until_channel_closed()
{
    msg="wait until $1 sees channel closed"
    cmd="./run_electrum_nmc --regtest -D /tmp/$1"
    while [[ $($cmd list_channels | jq '.[0].state' | tr -d '"') != "CLOSED" ]]; do
        sleep 1
	msg="$msg."
	printf "$msg\r"
    done
    printf "\n"
}

function wait_until_spent()
{
    msg="wait until $1:$2 is spent"
    while [[ $($bitcoin_cli gettxout $1 $2) ]]; do
        sleep 1
	msg="$msg."
	printf "$msg\r"
    done
    printf "\n"
}

if [[ $# -eq 0 ]]; then
    echo "syntax: init|start|open|status|pay|close|stop"
    exit 1
fi

if [[ $1 == "new_block" ]]; then
    new_blocks 1
fi

if [[ $1 == "init" ]]; then
    create_opts="$3"
    echo "initializing $2 $create_opts"
    rm -rf /tmp/$2/
    agent="./run_electrum_nmc --regtest -D /tmp/$2"
    $agent create $create_opts --offline > /dev/null
    $agent setconfig --offline log_to_file True
    $agent setconfig --offline server 127.0.0.1:51001:t
    if [[ "$create_opts" != *"standard"* ]]; then
    $agent setconfig --offline lightning_to_self_delay 144
    fi
    # alice is funded, bob is listening
    if [[ $2 == "bob" ]]; then
        if [[ "$create_opts" != *"standard"* ]]; then
        $bob setconfig --offline lightning_listen localhost:9735
        fi
    else
        echo "funding $2"
        $bitcoin_cli sendtoaddress $($agent getunusedaddress -o) 1
    fi
fi


# start daemons. Bob is started first because he is listening
if [[ $1 == "start" ]]; then
    agent="./run_electrum_nmc --regtest -D /tmp/$2"
    $agent daemon -d
    $agent load_wallet
    sleep 1 # give time to synchronize
fi

if [[ $1 == "stop" ]]; then
    agent="./run_electrum_nmc --regtest -D /tmp/$2"
    $agent stop || true

    # When testing GUI we need to close the windows when stopping the daemon
    if [[ ${ELECTRUM_MODE:-} == "GUI" ]]; then
        pid_file="/tmp/$2.pid"
        wine_pid_file="/tmp/$2.wine_pid"

 	# Check if the process with the stored PID exists and is running
        if [ -f "$pid_file" ]; then
            pid=$(<"$pid_file")
            kill $pid
	    echo "Stopping PID: $pid" 
            rm -f "$pid_file"
        fi

 	# Additional PID is be spawned during Windows tests. We terminate it here.
        if [[ ${Binaries:-} == "WINE" && -f "$wine_pid_file" ]]; then
            wine_pid=$(<"$wine_pid_file")
            kill $wine_pid
	    echo "Stopping PID: $wine_pid"
            rm -f "$wine_pid_file"
        fi
	sleep 10
    fi
fi

if [[ $1 == "forwarding" ]]; then
    $bob setconfig lightning_forward_payments true
    bob_node=$($bob nodeid)
    channel_id1=$($alice open_channel $bob_node 0.002 --push_amount 0.001)
    channel_id2=$($carol open_channel $bob_node 0.002 --push_amount 0.001)
    echo "mining 3 blocks"
    new_blocks 3
    sleep 10 # time for channelDB
    request=$($carol add_lightning_request 0.0001 -m "blah" | jq -r ".invoice")
    $carol setconfig test_fail_malformed_htlc true
    $alice lnpay $request
    request2=$($carol add_lightning_request 0.0001 -m "blah" | jq -r ".invoice")
    $carol setconfig test_fail_malformed_htlc false
    $alice lnpay $request2
    carol_balance=$($carol list_channels | jq -r '.[0].local_balance')
    echo "carol balance: $carol_balance"
    if [[ $carol_balance != 110000 ]]; then
        exit 1
    fi
    chan1=$($alice list_channels | jq -r ".[0].channel_point")
    chan2=$($carol list_channels | jq -r ".[0].channel_point")
    $alice close_channel $chan1
    $carol close_channel $chan2
fi

# alice sends two payments, then broadcast ctx after first payment.
# thus, bob needs to redeem both to_local and to_remote


if [[ $1 == "breach" ]]; then
    wait_for_balance alice 1
    echo "alice opens channel"
    bob_node=$($bob nodeid)
    channel=$($alice open_channel $bob_node 0.15)
    new_blocks 3
    wait_until_channel_open alice
    request=$($bob add_lightning_request 0.01 -m "blah" | jq -r ".invoice")
    echo "alice pays"
    $alice lnpay $request
    sleep 2
    ctx=$($alice get_channel_ctx $channel --iknowwhatimdoing)
    request=$($bob add_lightning_request 0.01 -m "blah2" | jq -r ".invoice")
    echo "alice pays again"
    $alice lnpay $request
    echo "alice broadcasts old ctx"
    $bitcoin_cli sendrawtransaction $ctx
    new_blocks 1
    wait_until_channel_closed bob
    new_blocks 1
    wait_for_balance bob 0.14
    $bob getbalance
fi


if [[ $1 == "extract_preimage" ]]; then
    # instead of settling bob will broadcast
    $bob enable_htlc_settle false
    wait_for_balance alice 1
    echo "alice opens channel"
    bob_node=$($bob nodeid)
    $alice open_channel $bob_node 0.15
    new_blocks 3
    wait_until_channel_open alice
    chan_id=$($alice list_channels | jq -r ".[0].channel_point")
    # alice pays bob
    invoice=$($bob add_lightning_request 0.04 -m "test" | jq -r ".invoice")
    screen -S alice_payment -dm -L -Logfile /tmp/alice/screen.log $alice lnpay $invoice --timeout=600
    sleep 1
    unsettled=$($alice list_channels | jq '.[] | .local_unsettled_sent')
    if [[ "$unsettled" == "0" ]]; then
        echo 'enable_htlc_settle did not work'
        exit 1
    fi
    # bob force closes
    $bob close_channel $chan_id --force
    new_blocks 1
    wait_until_channel_closed bob
    sleep 5
    success=$(cat /tmp/alice/screen.log | jq -r ".success")
    if [[ "$success" != "true" ]]; then
        exit 1
    fi
    cat /tmp/alice/screen.log
fi


if [[ $1 == "redeem_htlcs" ]]; then
    $bob enable_htlc_settle false
    wait_for_balance alice 1
    echo "alice opens channel"
    bob_node=$($bob nodeid)
    $alice open_channel $bob_node 0.15
    new_blocks 3
    wait_until_channel_open alice
    # alice pays bob
    invoice=$($bob add_lightning_request 0.04 -m "test" | jq -r ".invoice")
    $alice lnpay $invoice --timeout=1 || true
    unsettled=$($alice list_channels | jq '.[] | .local_unsettled_sent')
    if [[ "$unsettled" == "0" ]]; then
        echo 'enable_htlc_settle did not work'
        exit 1
    fi
    # bob goes away
    $bob stop
    echo "alice balance before closing channel:" $($alice getbalance)
    balance_before=$($alice getbalance | jq '[.confirmed, .unconfirmed, .lightning] | to_entries | map(select(.value != null).value) | map(tonumber) | add ')
    # alice force closes the channel
    chan_id=$($alice list_channels | jq -r ".[0].channel_point")
    $alice close_channel $chan_id --force
    new_blocks 1
    sleep 3
    echo "alice balance after closing channel:" $($alice getbalance)
    new_blocks 150
    sleep 10
    new_blocks 1
    sleep 3
    echo "alice balance after CLTV" $($alice getbalance)
    new_blocks 150
    sleep 10
    new_blocks 1
    sleep 3
    echo "alice balance after CSV" $($alice getbalance)
    # fixme: add local to getbalance
    wait_for_balance alice $(echo "$balance_before - 0.02" | bc -l)
    $alice getbalance
fi


if [[ $1 == "breach_with_unspent_htlc" ]]; then
    $bob enable_htlc_settle false
    wait_for_balance alice 1
    echo "alice opens channel"
    bob_node=$($bob nodeid)
    channel=$($alice open_channel $bob_node 0.15)
    new_blocks 3
    wait_until_channel_open alice
    echo "alice pays bob"
    invoice=$($bob add_lightning_request 0.04 -m "test" | jq -r ".invoice")
    $alice lnpay $invoice --timeout=1 || true
    unsettled=$($alice list_channels | jq '.[] | .local_unsettled_sent')
    if [[ "$unsettled" == "0" ]]; then
        echo "enable_htlc_settle did not work, $unsettled"
        exit 1
    fi
    ctx=$($alice get_channel_ctx $channel --iknowwhatimdoing)
    $bob enable_htlc_settle true
    unsettled=$($alice list_channels | jq '.[] | .local_unsettled_sent')
    if [[ "$unsettled" != "0" ]]; then
        echo "enable_htlc_settle did not work, $unsettled"
        exit 1
    fi
    echo "alice breaches with old ctx"
    $bitcoin_cli sendrawtransaction $ctx
    wait_for_balance bob 0.14
fi


if [[ $1 == "breach_with_spent_htlc" ]]; then
    $bob enable_htlc_settle false
    wait_for_balance alice 1
    echo "alice opens channel"
    bob_node=$($bob nodeid)
    channel=$($alice open_channel $bob_node 0.15)
    new_blocks 3
    wait_until_channel_open alice
    echo "alice pays bob"
    invoice=$($bob add_lightning_request 0.04 -m "test" | jq -r ".invoice")
    $alice lnpay $invoice --timeout=1 || true
    ctx=$($alice get_channel_ctx $channel --iknowwhatimdoing)
    unsettled=$($alice list_channels | jq '.[] | .local_unsettled_sent')
    if [[ "$unsettled" == "0" ]]; then
        echo "enable_htlc_settle did not work, $unsettled"
        exit 1
    fi
    cp /tmp/alice/regtest/wallets/default_wallet /tmp/alice/regtest/wallets/toxic_wallet
    $bob enable_htlc_settle true
    unsettled=$($alice list_channels | jq '.[] | .local_unsettled_sent')
    if [[ "$unsettled" != "0" ]]; then
        echo "enable_htlc_settle did not work, $unsettled"
        exit 1
    fi
    echo $($bob getbalance)
    echo "bob goes offline"
    $bob stop
    ctx_id=$($bitcoin_cli sendrawtransaction $ctx)
    echo "alice breaches with old ctx:" $ctx_id
    new_blocks 1
    if [[ $($bitcoin_cli gettxout $ctx_id 0 | jq '.confirmations') != "1" ]]; then
        echo "breach tx not confirmed"
        exit 1
    fi
    echo "wait for cltv_expiry blocks"
    # note: this will let alice redeem both to_local and the htlc.
    # (to_local needs to_self_delay blocks; htlc needs whatever we put in invoice)
    new_blocks 150
    $alice stop
    $alice daemon -d
    sleep 1
    $alice load_wallet -w /tmp/alice/regtest/wallets/toxic_wallet
    # wait until alice has spent both ctx outputs
    echo "alice spends to_local and htlc outputs"
    wait_until_spent $ctx_id 0
    wait_until_spent $ctx_id 1
    new_blocks 1
    echo "bob comes back"
    $bob daemon -d
    sleep 1
    $bob load_wallet
    wait_for_balance bob 0.039
    $bob getbalance
fi


if [[ $1 == "configure_test_watchtower" ]]; then
    # carol is the watchtower of bob
    $carol setconfig -o run_local_watchtower true
    $carol setconfig -o watchtower_user wtuser
    $carol setconfig -o watchtower_password wtpassword
    $carol setconfig -o watchtower_address 127.0.0.1:12345
    $bob setconfig -o watchtower_url http://wtuser:wtpassword@127.0.0.1:12345
fi

if [[ $1 == "watchtower" ]]; then
    wait_for_balance alice 1
    echo "alice opens channel"
    bob_node=$($bob nodeid)
    channel=$($alice open_channel $bob_node 0.15)
    echo "channel outpoint: $channel"
    new_blocks 3
    wait_until_channel_open alice
    echo "alice pays bob"
    invoice1=$($bob add_lightning_request 0.01 -m "invoice1" | jq -r ".invoice")
    $alice lnpay $invoice1
    ctx=$($alice get_channel_ctx $channel --iknowwhatimdoing)
    echo "alice pays bob again"
    invoice2=$($bob add_lightning_request 0.01 -m "invoice2" | jq -r ".invoice")
    $alice lnpay $invoice2
    msg="waiting until watchtower is synchronized"
    while watchtower_ctn=$($carol get_watchtower_ctn $channel) && [ $watchtower_ctn != "3" ]; do
        sleep 1
	msg="$msg."
	printf "$msg\r"
    done
    printf "\n"
fi

if [[ $1 == "unixsockets" ]]; then
    # This looks different because it has to run the entire daemon
    # Test domain socket behavior
    ./run_electrum_nmc --regtest daemon -d --rpcsock=unix # Start daemon with unix domain socket
    ./run_electrum_nmc --regtest stop # Errors if it can't connect
    # Test custom socket path
    f=$(mktemp -u /tmp/electrum_test.XXXX)
    ./run_electrum_nmc --regtest daemon -d --rpcsock=unix --rpcsockpath=$f
    [ -S $f ] # filename exists and is socket
    ./run_electrum_nmc --regtest stop
    rm $f # clean up
    # Test for regressions in the ordinary TCP functionality.
    ./run_electrum_nmc --regtest daemon -d --rpcsock=tcp
    ./run_electrum_nmc --regtest stop
fi

function name_new_broadcast()
{
    user=$1
    args=$2
    new_output=$($user name_new $args)
    new_tx=$(echo $new_output | jq -r .tx)
    $user addtransaction $new_tx > /dev/null
    $user broadcast $new_tx > /dev/null
    echo $new_output
}

function name_firstupdate_broadcast()
{
    user=$1
    args=$2
    firstupdate_tx=$($user name_firstupdate $args)
    $user addtransaction $firstupdate_tx > /dev/null
    firstupdate_txid=$($user broadcast $firstupdate_tx)
    echo $firstupdate_txid
}

function wait_for_chain_sync()
{
    user=$1

    while true; do
        core_height=$($bitcoin_cli getblockcount)
        electrumx_height=$($user getinfo | jq -r .server_height)
        wallet_height=$($user getinfo | jq -r .blockchain_height)

        echo "Core, ElectrumX, Wallet heights: $core_height $electrumx_height $wallet_height"
        if [[ "$core_height" == "$electrumx_height" ]] && [[ "$core_height" == "$wallet_height" ]]; then
            break
        fi

        sleep 1
    done
}

function assert_equal()
{
    err_msg="$3"

    if [[ "$1" != "$2" ]]; then
        echo "'$1' != '$2'"
        echo "$err_msg"
        return 1
    fi
}

function assert_raises_error()
{
    cmd=$1
    required_err=$2

    if observed_err=$($cmd 2>&1) ; then
        echo "Failed to raise error '$required_err'"
        return 1
    fi
    if [[ "$observed_err" != *"$required_err"* ]]; then
        echo "$observed_err"
        echo "Raised wrong error instead of '$required_err'"
        return 1
    fi
}

function assert_core_expired()
{
    expired_name=$1

    echo "TODO: Upgrade Namecoin Core version"
    name_result=$($bitcoin_cli name_show $expired_name)
    name_result_expired=$(echo $name_result | jq -r .expired)
    assert_equal $name_result_expired true "Name not expired"
}

function assert_core_nx()
{
    nx_name=$1

    assert_raises_error "$bitcoin_cli name_show $nx_name" "name not found" || assert_core_expired "$nx_name"
}

function assert_electrum_nx()
{
    nx_user=$1
    nx_name=$2

    assert_raises_error "$user name_show $nx_name" "Name purportedly never existed" || assert_raises_error "$user name_show $nx_name" "Name is purportedly expired"
}

# Equivalent to Namecoin Core's name_registration.py functional test.
if [[ $1 == "name_registration" ]]; then
    # Expire any existing names from previous functional test runs.
    new_blocks 35
    wait_for_chain_sync "$alice"
    echo "Perform name_new's.  Check for too long names exception."
    #newA = node.name_new ("name-0")
    newA=$(name_new_broadcast "$alice" "--identifier name-0")
    #newAconfl = node.name_new ("name-0")
    newAconfl=$(name_new_broadcast "$alice" "--identifier name-0")
    #addr = node.getnewaddress ()
    addr=$($alice add_request 0 | jq -r .address)
    echo $addr
    #newB = node.name_new ("name-1", {"destAddress": addr})
    newB=$(name_new_broadcast "$alice" "--identifier name-1 --destination $addr")
    #node.name_new ("x" * 255)
    name_new_broadcast "$alice" "--identifier $(printf %255s | tr ' ' 'x')"
    #assert_raises_rpc_error (-8, 'name is too long', node.name_new, "x" * 256)
    assert_raises_error "$alice name_new --identifier $(printf %256s | tr ' ' 'x')" "identifier length 256 exceeds limit of 255"
    #self.generateToOther (5)
    new_blocks 5
    wait_for_chain_sync "$alice"

    echo "Verify that the name_new with explicit address sent really to this"
    echo "address.  Since there is no equivalent to name_show while we only"
    echo "have a name_new, explicitly check the raw tx."
    #txHex = node.gettransaction (newB[0])['hex']
    txHex=$(echo $newB | jq -r .tx)
    #newTx = node.decoderawtransaction (txHex)
    newTx=$($alice deserialize $txHex)
    #found = False
    found=0
    #for out in newTx['vout']:
    newTx_outputs=$(echo $newTx | jq -r .outputs)
    newTx_outputs_len=$(echo $newTx_outputs | jq -r length)
    for ((index=0; index<$newTx_outputs_len; index++)); do
        out=$(echo $newTx_outputs | jq -r .[$index])
        # if 'nameOp' in out['scriptPubKey']:
        out_name_op=$(echo $out | jq -r .name_op)
        if [[ "$out_name_op" != "null" ]]; then
            # assert not found
            assert_equal "$found" 0 "multiple name ops found"
            # found = True
            found=1
            # assert_equal (out['scriptPubKey']['addresses'], [addr])
            out_addr=$(echo $out | jq -r .address)
            assert_equal "$out_addr" "$addr" "wrong address"
        fi
    done
    #assert found
    assert_equal "$found" 1 "no name op found"

    echo "Check for exception with name_history and without -namehistory."
    echo "TODO: Electrum-NMC doesn't support name_history yet."

    echo "first_update the names.  Check for too long values."
    #addr = node.getnewaddress ()
    addr=$($alice add_request 0 | jq -r .address)
    echo $addr
    #txidA = self.firstupdateName (0, "name-0", newA, "value-0",
    #                              {"destAddress": addr})
    # TODO: Here, we use a deterministic salt, whereas Namecoin Core uses
    # non-DS.  Should probably test both DS and non-DS cases once Namecoin Core
    # tests both.
    txidA=$(name_firstupdate_broadcast "$alice" "name-0 --value value-0 --destination $addr --allow_early")
    #assert_raises_rpc_error (-8, 'value is too long',
    #                         self.firstupdateName, 0, "name-1", newB, "x" * 521)
    assert_raises_error "$alice name_firstupdate name-1 --value $(printf %521s | tr ' ' 'x') --allow_early" "value length 521 exceeds limit of 520"
    #self.firstupdateName (0, "name-1", newB, "x" * 520)
    name_firstupdate_broadcast "$alice" "name-1 --value $(printf %520s | tr ' ' 'x') --allow_early"

    echo 'Check for mempool conflict detection with registration of "name-0".'
    #assert_raises_rpc_error (-25, 'is already being registered',
    #                         self.firstupdateName,
    #                         0, "name-0", newAconfl, "foo")
    firstupdate_confl=$($alice name_firstupdate name-0 --value foo --allow_early)
    assert_raises_error "$alice broadcast $firstupdate_confl" "txn-mempool-name-error"

    echo "Check that the name appears when the name_new is ripe."
    #self.generateToOther (7)
    new_blocks 7
    wait_for_chain_sync "$alice"
    #assert_raises_rpc_error (-4, 'name not found',
    #                         node.name_show, "name-0")
    assert_core_nx "name-0"
    assert_electrum_nx "$alice" "name-0"
    #assert_raises_rpc_error (-4, 'name not found',
    #                         node.name_history, "name-0")
    echo "TODO: Electrum-NMC doesn't support name_history yet."
    #self.generateToOther (1)
    new_blocks 1
    wait_for_chain_sync "$alice"

    #data = self.checkName (0, "name-0", "value-0", 30, False)
    data_core=$($bitcoin_cli name_show name-0)
    data_core_name=$(echo $data_core | jq -r .name)
    assert_equal "$data_core_name" "name-0" "Wrong name"
    data_core_value=$(echo $data_core | jq -r .value)
    assert_equal "$data_core_value" "value-0" "Wrong value"
    data_core_expires_in=$(echo $data_core | jq -r .expires_in)
    assert_equal "$data_core_expires_in" "30" "Wrong expires_in"
    data_core_expired=$(echo $data_core | jq -r .expired)
    assert_equal "$data_core_expired" "false" "Wrong expired"
    assert_raises_error "$alice name_show name-0" "Name is purportedly unconfirmed"
    #assert_equal (data['address'], addr)
    data_core_address=$(echo $data_core | jq -r .address)
    assert_equal "$data_core_address" "$addr" "Wrong address"
    #assert_equal (data['txid'], txidA)
    data_core_txid=$(echo $data_core | jq -r .txid)
    assert_equal "$data_core_txid" "$txidA" "Wrong txid"
    #assert_equal (data['height'], 213)
    echo "Skipping height field."

    #self.checkNameHistory (0, "name-0", ["value-0"])
    echo "TODO: Electrum-NMC doesn't support name_history yet."
    #self.checkNameHistory (0, "name-1", ["x" * 520])
    echo "TODO: Electrum-NMC doesn't support name_history yet."

    echo "Add enough confirmations to make Electrum-NMC happy."
    new_blocks 11
    wait_for_chain_sync "$alice"
    data_core=$($bitcoin_cli name_show name-0)
    data_electrum=$($alice name_show name-0)
    assert_equal "$(echo $data_core | jq -r .name)" "$(echo $data_electrum | jq -r .name)" "Core/Electrum mismatched name"
    assert_equal "$(echo $data_core | jq -r .value)" "$(echo $data_electrum | jq -r .value)" "Core/Electrum mismatched value"
    assert_equal "$(echo $data_core | jq -r .txid)" "$(echo $data_electrum | jq -r .txid)" "Core/Electrum mismatched txid"
    assert_equal "$(echo $data_core | jq -r .vout)" "$(echo $data_electrum | jq -r .vout)" "Core/Electrum mismatched vout"
    assert_equal "$(echo $data_core | jq -r .address)" "$(echo $data_electrum | jq -r .address)" "Core/Electrum mismatched address"
    assert_equal "$(echo $data_core | jq -r .height)" "$(echo $data_electrum | jq -r .height)" "Core/Electrum mismatched height"
    assert_equal "$(echo $data_core | jq -r .expires_in)" "$(echo $data_electrum | jq -r .expires_in)" "Core/Electrum mismatched expires_in"
    assert_equal "$(echo $data_core | jq -r .expired)" "$(echo $data_electrum | jq -r .expired)" "Core/Electrum mismatched expired"

    echo "TODO: test semi_expires_in=1 and semi_expires_in=0 once they're added to Namecoin Core"

    echo "Add enough confirmations for expires_in=1"
    echo "TODO: skipping expires_in=1 test until allowExpired is implemented"
    exit 0
    new_blocks 18
    wait_for_chain_sync "$alice"
    data_core=$($bitcoin_cli name_show name-0)
    assert_equal "$(echo $data_core | jq -r .expires_in)" 1 "Wrong expires_in"
    assert_equal "$(echo $data_core | jq -r .expired)" false "Wrong expired"
    data_electrum=$($alice name_show name-0)
    assert_equal "$(echo $data_core | jq -r .name)" "$(echo $data_electrum | jq -r .name)" "Core/Electrum mismatched name"
    assert_equal "$(echo $data_core | jq -r .value)" "$(echo $data_electrum | jq -r .value)" "Core/Electrum mismatched value"
    assert_equal "$(echo $data_core | jq -r .txid)" "$(echo $data_electrum | jq -r .txid)" "Core/Electrum mismatched txid"
    assert_equal "$(echo $data_core | jq -r .vout)" "$(echo $data_electrum | jq -r .vout)" "Core/Electrum mismatched vout"
    assert_equal "$(echo $data_core | jq -r .address)" "$(echo $data_electrum | jq -r .address)" "Core/Electrum mismatched address"
    assert_equal "$(echo $data_core | jq -r .height)" "$(echo $data_electrum | jq -r .height)" "Core/Electrum mismatched height"
    assert_equal "$(echo $data_core | jq -r .expires_in)" "$(echo $data_electrum | jq -r .expires_in)" "Core/Electrum mismatched expires_in"
    assert_equal "$(echo $data_core | jq -r .expired)" "$(echo $data_electrum | jq -r .expired)" "Core/Electrum mismatched expired"

    echo "Add enough confirmations for expires_in=0"
    new_blocks 1
    wait_for_chain_sync "$alice"
    assert_core_nx "name-0"
    assert_electrum_nx "$alice" "name-0"







    echo "TODO: Finish these tests"








    # Verify the allowExisting option for name_new.
    #assert_raises_rpc_error (-25, 'exists already',
    #                         node.name_new, "name-0")
    #assert_raises_rpc_error (-25, 'exists already',
    #                         node.name_new, "name-0",
    #                         {"allowExisting": False})
    #assert_raises_rpc_error (-3, 'Expected type bool for allowExisting',
    #                         node.name_new, "other",
    #                         {"allowExisting": 42.5})
    #node.name_new ("name-0", {"allowExisting": True})









fi

if [[ $1 == "name_autoregister" ]]; then
    # Expire any existing names from previous functional test runs.
    new_blocks 35
    wait_for_chain_sync "$alice"
    echo "Perform name_new's.  Check for too long names exception."
    #newA = node.name_new ("name-0")
    $alice name_autoregister "name-0"
    #newAconfl = node.name_new ("name-0")
    # Skip this line for name_autoregister
    #addr = node.getnewaddress ()
    addr=$($alice add_request 0 | jq -r .address)
    echo $addr
    #newB = node.name_new ("name-1", {"destAddress": addr})
    $alice name_autoregister "name-1" --destination "$addr"
    #node.name_new ("x" * 255)
    $alice name_autoregister "$(printf %255s | tr ' ' 'x')"
    #assert_raises_rpc_error (-8, 'name is too long', node.name_new, "x" * 256)
    assert_raises_error "$alice name_autoregister $(printf %256s | tr ' ' 'x')" "identifier length 256 exceeds limit of 255"
    #self.generateToOther (5)
    new_blocks 5
    wait_for_chain_sync "$alice"

    echo "TODO: Finish these tests"
fi

if [[ $1 == "name_ant_workflow" ]]; then
    # Expire any existing names from previous functional test runs.
    new_blocks 35
    wait_for_chain_sync "$alice"
    wait_for_chain_sync "$bob"

    echo "funding Bob"
    $bitcoin_cli sendtoaddress $($bob getunusedaddress -o) 1

    echo "Alice registers name"
    $alice name_autoregister "x/name" --value "value"
    sleep 5
    new_blocks 12
    wait_for_chain_sync "$alice"
    wait_for_chain_sync "$bob"
    # TODO: Remove this line once daemon mode automatically does this.
    $alice updatequeuedtransactions
    sleep 5
    new_blocks 12
    wait_for_chain_sync "$alice"
    wait_for_chain_sync "$bob"
    data_alice=$($alice name_show x/name -w /tmp/alice/regtest/wallets/default_wallet)
    data_bob=$($bob name_show x/name -w /tmp/bob/regtest/wallets/default_wallet)
    assert_equal "true" "$(echo $data_alice | jq -r .ismine)" "Newly registered Alice name doesn't belong to Alice"
    assert_equal "false" "$(echo $data_bob | jq -r .ismine)" "Newly registered Alice name belongs to Bob"

    echo "Alice sells to Bob"
    offer=$($alice name_sell x/name 0.02)
    assert_raises_error "$bob name_buy x/name 0.01 --value value2 --offer $offer" "price mismatch"
    assert_raises_error "$bob name_buy x/name 0.02 --value value2 --offer $offer" "price mismatch"
    assert_raises_error "$bob name_buy x/name2 0.04 --value value2 --offer $offer" "name identifier mismatch"
    completed_offer=$($bob name_buy x/name 0.04 --value value2 --offer $offer)
    $bob broadcast $completed_offer
    sleep 5
    new_blocks 12
    wait_for_chain_sync "$alice"
    wait_for_chain_sync "$bob"
    data_alice=$($alice name_show x/name -w /tmp/alice/regtest/wallets/default_wallet)
    data_bob=$($bob name_show x/name -w /tmp/bob/regtest/wallets/default_wallet)
    assert_equal "false" "$(echo $data_alice | jq -r .ismine)" "Transferred Bob name belongs to Alice"
    assert_equal "true" "$(echo $data_bob | jq -r .ismine)" "Transferred Bob name doesn't belong to Bob"

    echo "Alice buys from Bob"
    offer=$($alice name_buy x/name 0.02 --value value3)
    assert_raises_error "$bob name_sell x/name 0.03 --offer $offer" "price mismatch"
    assert_raises_error "$bob name_sell x/name 0.02 --offer $offer" "price mismatch"
    assert_raises_error "$bob name_sell x/name2 0.005 --offer $offer" "name identifier mismatch"
    completed_offer=$($bob name_sell x/name 0.005 --offer $offer)
    $bob broadcast $completed_offer
    sleep 5
    new_blocks 12
    wait_for_chain_sync "$alice"
    wait_for_chain_sync "$bob"
    data_alice=$($alice name_show x/name -w /tmp/alice/regtest/wallets/default_wallet)
    data_bob=$($bob name_show x/name -w /tmp/bob/regtest/wallets/default_wallet)
    assert_equal "true" "$(echo $data_alice | jq -r .ismine)" "Transferred Alice name doesn't belong to Alice"
    assert_equal "false" "$(echo $data_bob | jq -r .ismine)" "Transferred Alice name belongs to Bob"
fi
