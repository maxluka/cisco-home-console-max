#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

bashio::log.info "Starting Cisco Home Console Max"

cd /opt/app || bashio::exit.nok "Application directory is missing."

# Access logging off: the phones re-fetch the dashboard constantly and the
# add-on log is for events, not traffic.
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log
