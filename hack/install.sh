#!/usr/bin/env bash

kvmd_dir=/usr/lib/python3.11/site-packages
src_dir=/home/appkins/src/appkins-org/kvmd
ssh root@pikvm 'rw'
patch_files=(
    "kvmd/plugins/ugpio/unifi.py"
    "kvmd/apps/kvmd/server.py"
    "kvmd/apps/kvmd/api/redfish.py"
)
for item in "${patch_files[@]}"; do
  echo "root@pikvm:"${kvmd_dir}/${item}""
  scp "${src_dir}/${item}" root@pikvm:"${kvmd_dir}/${item}"
done
scp "${src_dir}/override.yaml" root@pikvm:/etc/kvmd/override.yaml
ssh root@pikvm 'ro && systemctl restart kvmd'

cp unifi.py /usr/lib/python3.11/site-packages/kvmd/plugins/ugpio/unifi.py


scp root@pikvm:/etc/kvmd/override.yaml /home/appkins/src/appkins-org/kvmd-plugins/override.yaml

ssh root@pikvm 'rw'
scp /home/appkins/src/appkins-org/kvmd-plugins/override.yaml root@pikvm:/etc/kvmd/override.yaml
ssh root@pikvm 'ro && systemctl restart kvmd'