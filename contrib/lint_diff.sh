#!/usr/bin/env bash

set -euo pipefail
shopt -s nullglob

# Prereqs:
# sudo apt install flake8
# go install -v github.com/bradleyfalzon/revgrep/cmd/revgrep@master

CURRENT_BRANCH="$(git branch --show-current)"

if echo "${CURRENT_BRANCH}" | grep auxpow > /dev/null
then
	BASE_BRANCH="$(echo ${CURRENT_BRANCH} | sed s/auxpow/bitcoin/)"
	echo "Current auxpow branch: $CURRENT_BRANCH, base bitcoin branch: $BASE_BRANCH"
else
	if echo "${CURRENT_BRANCH}" | grep master > /dev/null
	then
		BASE_BRANCH="$(echo ${CURRENT_BRANCH} | sed s/master/auxpow/)"
		echo "Current master branch: $CURRENT_BRANCH, base auxpow branch: $BASE_BRANCH"
	else
		# We may be on a non-branch commit.
		CURRENT_BRANCH="$(git rev-parse HEAD)"
		MASTER_AUXPOW="$(echo electrum_*/electrum/auxpow.py)"
		if [ "${MASTER_AUXPOW}" != "" ] && [ -e electrum_*/electrum/auxpow.py ]
		then
			LOG="$(git log --pretty="format:%H %s" | grep "Merge branch 'auxpow" | head --lines=1)" || true
			MERGE_BRANCH="$(echo "${LOG}" | cut --delimiter=" " --fields=1 )"
			BASE_BRANCH=$(git rev-parse ${MERGE_BRANCH}^2)

			echo "Current master branch: $CURRENT_BRANCH, base auxpow branch: $BASE_BRANCH"
		else
			if [[ -e electrum/auxpow.py ]]
			then
				LOG="$(git log --pretty="format:%H %s" | grep "Merge branch 'bitcoin" | head --lines=1)" || true
				MERGE_BRANCH="$(echo "${LOG}" | cut --delimiter=" " --fields=1 )"
				BASE_BRANCH=$(git rev-parse ${MERGE_BRANCH}^2)

				echo "Current auxpow branch: $CURRENT_BRANCH, base bitcoin branch: $BASE_BRANCH"
			else
				echo "Unrecognized current branch: ${CURRENT_BRANCH}"
				exit 1
			fi
		fi
	fi
fi

flake8 . --select E,F,W,C90 --extend-ignore E501 --extend-exclude ./electrum_nmc/electrum/null_impl,./electrum_nmc/electrum/gui/qt/forms,./packages |& revgrep -regexp '\./(.*?):([0-9]+):([0-9]+)?:?\s*(.*)' "${BASE_BRANCH}" "${CURRENT_BRANCH}"
