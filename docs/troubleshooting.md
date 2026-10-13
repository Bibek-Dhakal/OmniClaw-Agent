# Troubleshooting

Start with the Web Logs Dashboard at `http://localhost:8080/logs` and `docker compose logs -f omniclaw`.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `No connected apps found` at startup | Wrong `COMPOSIO_USER_ID`, account not ACTIVE, or Nango connection missing | Match `COMPOSIO_USER_ID` to the connected account's user id. Check the account status. |
| Tool error `No connected account found for user ID ...` (404) | Same user id mismatch | Same fix. Then `docker compose up -d --force-recreate`. |
| `Cannot connect to host host.docker.internal:<port>` | LLM or Nango server not running, bound to 127.0.0.1 only, wrong port, or firewall | Start it, bind to `0.0.0.0`, check the port, allow it in the firewall. |
| `host.docker.internal` not found (Linux) | Name not provided by Docker on Linux | Handled by `extra_hosts` in `docker-compose.yml`. Make sure you have the latest file. |
| "Something went wrong while handling that" | Any exception in the pipeline | Read `docker compose logs omniclaw`. The traceback names the failing call. |
| LiteLLM `AuthenticationError` or 401 | Wrong or empty `LLM_API_KEY`, or wrong model prefix | Check the key and `LLM_MODEL` (for example `gemini/...` or `openai/...`). |
| Bot never answers | Your id is not in `TELEGRAM_ALLOWED_USER_IDS` | Use your numeric id, comma-separated, no spaces. The log shows "unauthorized user". |
| `/start` does nothing | Slash commands are ignored | Send a normal message. |
| Changes to `.env` ignored | Container not recreated | `docker compose up -d --force-recreate`. |
| Fewer results than asked | The account really has fewer, or the result was cut off | Check `/logs`. The bot says so when a result ends with `[truncated]`. |
| Nango: "No Nango connection found" | Provider id mismatch or no connection | Align integration ids with `PROVIDERS` in `nango_tools.py` and create a connection. |
| Approval never arrives | Message went to another chat | Reply YES or NO in the same chat. It times out after `APPROVAL_TIMEOUT_SECONDS`. |
| Browser refuses a site | Domain not allowlisted | Add it to `BROWSER_ALLOWED_DOMAINS`. |

## Checking a connector without the LLM

Look at the startup line `Connected apps: [...]`. If your app is listed, discovery works.
If it is not listed, the model never gets its tools, so fix the connector first.