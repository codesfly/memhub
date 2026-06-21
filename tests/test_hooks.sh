#!/bin/bash
# Verify hooks never crash regardless of input or service state.
set -e
chmod +x hooks/memhub-capture.sh hooks/memhub-inject.sh
echo '{}' | ./hooks/memhub-capture.sh                                          # empty
echo '{"transcript_path":"/nonexistent","cwd":"/tmp","session_id":"s"}' | ./hooks/memhub-capture.sh  # bad path
echo 'not json' | ./hooks/memhub-capture.sh                                    # bad json
echo '{}' | ./hooks/memhub-inject.sh                                           # empty
echo '{"cwd":"/tmp"}' | ./hooks/memhub-inject.sh >/dev/null                     # may output JSON or nothing; must exit 0
echo "hooks smoke OK"
