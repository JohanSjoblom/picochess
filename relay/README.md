# Experimental Picochess relay

This MVP relays moves between two Picochess instances configured with
`noeboard`. It uses the existing `/event` websocket and `/channel` HTTP API.
It does not configure or synchronize clocks, engines, colours, modes, or new
games.

The relay supports standard chess only. A stopped relay does not reconnect;
correct the problem and start it again.

## Run

Use the virtual environment of the local Picochess installation:

```bash
cd /opt/picochess
source venv/bin/activate
python -m relay http://pico-a:8080 http://pico-b:8080
```

Starting the command arms the relay. It prints `ARMED` only after it has
connected to both instances and verified that their complete FEN positions are
identical.

## Match setup

1. Configure the same time control on both instances.
2. Select the engines.
3. Start a new game on both.
4. Keep the future White-engine instance as user White initially.
5. Configure the other instance as user White, so its engine plays Black.
6. Start the relay and wait for `ARMED`.
7. Press **Switch Sides** on the future White-engine instance.

The relay forwards only `play=computer` moves. It consumes matching
`play=user` events as acknowledgements but never forwards them. It stops on a
new game, game end, connection loss, rejected move, or any position mismatch.
The default acknowledgement timeout is 10 seconds and can be changed with
`--timeout`.
