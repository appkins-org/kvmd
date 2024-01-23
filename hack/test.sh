#!/usr/bin/env bash

test_redfish() {

  for p in $(curl -s -k -u admin:admin https://pikvm/api/redfish/v1/Systems | jq -r '.Members[]["@odata.id"]'); do
    system="$(basename $p)"
    echo "Getting config for $system"
    curl -s -k -u admin:admin https://pikvm/api/redfish/v1/Systems/"$system"
  done

}

test_redfish

# curl -s -k -u admin:admin -H "Content-Type: application/json" --data '{"ResetType": "ForceRestart"}' --request POST https://pikvm/api/redfish/v1/Systems/server3/Actions/ComputerSystem.Reset

# curl -s -k -u admin:admin https://pikvm/api/redfish/v1/Systems -H "If-Match: Etag"