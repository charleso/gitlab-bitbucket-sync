#!/bin/sh -eu

###
# A very poor-man's unbounded queue for processing lines in a file idempotently.
# If the process crashes and is restart it will continue from the line it last
# saw.
#
# > QUEUE=/tmp/q QUEUE_INDEX=/tmp/q.i queue.sh echo
#
# FIXME Add file rotation
###

: ${QUEUE:?QUEUE}
: ${QUEUE_INDEX:?QUEUE_INDEX}

INDEX=$(cat "$QUEUE_INDEX" 2> /dev/null || echo "1")
touch "$QUEUE"

tail -n "+${INDEX}" -f "$QUEUE" | while read -r line; do
  "$@" "$line"
  INDEX=$(expr $INDEX + 1)
  echo $INDEX > "$QUEUE_INDEX"
done
