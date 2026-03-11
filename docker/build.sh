#!/bin/bash


docker compose down
rm data/iceshake.fdb
time docker compose -f compose.yaml  build
docker compose up -d
# log into docker container
# docker exec -it icecast-fsg bash
