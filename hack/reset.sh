#!/usr/bin/env bash

kvmd_dir=/usr/lib/python3.11/site-packages
src_dir=/home/appkins/src/appkins-org/kvmd

ssh root@pikvm 'rw'
sleep 0.5

scp "${src_dir}/hack/reset.yaml" root@pikvm:/etc/kvmd/override.yaml
ssh root@pikvm 'ro && systemctl restart kvmd'
