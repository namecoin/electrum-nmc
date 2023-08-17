#!/usr/bin/env bash

set -euo pipefail
shopt -s failglob

# Prereqs:
# sudo apt install flake8
# go install -v github.com/bradleyfalzon/revgrep/cmd/revgrep@master

CURRENT_BRANCH="$(git branch --show-current)"

if echo "${CURRENT_BRANCH}" | grep auxpow > /dev/null
then
	BASE_BRANCH="$(echo ${CURRENT_BRANCH} | sed s/auxpow/bitcoin/)"
else
	if echo "${CURRENT_BRANCH}" | grep master > /dev/null
	then
		BASE_BRANCH="$(echo ${CURRENT_BRANCH} | sed s/master/auxpow/)"
	else
		echo "Unrecognized current branch: ${CURRENT_BRANCH}"
		exit 1
	fi
fi

flake8 . --select E,F,W,C90 --extend-ignore E501 --extend-exclude ./electrum_nmc/electrum/null_impl |& revgrep -regexp '\./(.*?):([0-9]+):([0-9]+)?:?\s*(.*)' "${BASE_BRANCH}" "${CURRENT_BRANCH}"
