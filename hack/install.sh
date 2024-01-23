#!/usr/bin/env bash

kvmd_dir=/usr/lib/python3.11/site-packages
src_dir=/home/appkins/src/appkins-org/kvmd

ssh root@pikvm 'rw'
sleep 0.5
patch_files=(
    "kvmd/plugins/ugpio/unifi.py"
    "kvmd/apps/kvmd/server.py"
    "kvmd/apps/kvmd/api/redfish.py"
)
for item in "${patch_files[@]}"; do
  echo "root@pikvm:"${kvmd_dir}/${item}""
  scp "${src_dir}/${item}" root@pikvm:"${kvmd_dir}/${item}"
done
scp "${src_dir}/hack/override.yaml" root@pikvm:/etc/kvmd/override.yaml
ssh root@pikvm 'ro && systemctl restart kvmd'
sleep 0.5


kvmd_dir=/usr/lib/python3.11/site-packages
src_dir=/home/appkins/src/appkins-org/kvmd
until ssh root@pikvm 'rw'
do
   sleep 1
   echo "Trying again. Try #$counter"
done
scp "${src_dir}/hack/override.yaml" root@pikvm:/etc/kvmd/override.yaml
ssh root@pikvm 'ro && systemctl restart kvmd'


until ssh root@pikvm 'journalctl -xeu kvmd -f'
do
   sleep 1
   echo "Trying again. Try #$counter"
done