#!/usr/bin/env bash

test_redfish() {

  for p in $(curl -s -k -u admin:admin https://pikvm/api/redfish/v1/Systems | jq -r '.Members[]["@odata.id"]'); do
    system="$(basename $p)"
    echo "Getting config for $system"
    curl -s -k -u admin:admin https://pikvm/api/redfish/v1/Systems/"$system"
  done

}

test_redfish
