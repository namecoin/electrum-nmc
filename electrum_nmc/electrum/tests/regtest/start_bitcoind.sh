#!/usr/bin/env bash
export HOME=~
set -eux pipefail
mkdir -p ~/.namecoin
cat > ~/.namecoin/namecoin.conf <<EOF
regtest=1
txindex=1
printtoconsole=1
rpcuser=doggman
rpcpassword=donkey
rpcallowip=127.0.0.1
zmqpubrawblock=tcp://127.0.0.1:28332
zmqpubrawtx=tcp://127.0.0.1:28333
debug=1
[regtest]
rpcbind=0.0.0.0
rpcport=18554
debug=1
EOF
rm -rf ~/.namecoin/regtest
screen -S namecoind -X quit || true
screen -S namecoind -m -d namecoind -regtest
sleep 6
addr=$(namecoin-cli getnewaddress)
namecoin-cli generatetoaddress 150 $addr > /dev/null

# Namecoin Core 0.18.0 activates SegWit on Regtest at height 432.  So we need
# to be at least that height for SegWit transactions to be mined.
# TODO: Remove this after we migrate the Regtest Travis job to a newer Namecoin
# Core.
# UPDATE: This is removed since Namecoin Core is now 0.19.0.
#namecoin-cli generatetoaddress 450 $addr > /dev/null
