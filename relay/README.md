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

## Physical eboard Remote engine match MVP

When `remote-picochess-url` is configured, selecting `Remote` uses one physical
eboard as the shared board for two engines. The local Picochess runs the White
engine. A second Picochess instance runs the Black engine in NOEBOARD mode.
Without this setting, Remote mode keeps its traditional behavior.

A cold-started remote Picochess may not yet publish a board position. During
this MVP, a connected peer that remains silent for two seconds is assumed to
be at the standard starting position. Any position it does publish is still
validated normally.

Current MVP limitations are intentional:

- standard chess and the normal starting position only;
- the local engine is White and the remote engine is Black;
- both instances must use fixed move time;
- clocks, engine selection and recovery are not synchronized;
- there is no reconnect, takeback, alternative move or position setup;
- the remote instance must be reachable without authentication.

Configure the physical-board instance in `picochess.ini`:

```ini
remote-picochess-url = http://pico-remote:8080
```

Test sequence:

1. Start the remote Picochess with NOEBOARD.
2. Select the engines and the same fixed move time on both instances.
3. Start a new standard game on both. Leave both as user White.
4. On the physical-board Picochess, select **Remote**. Wait for
   `Remote ready`.
5. As the final action, press **Switch Sides** on the physical-board instance.
   Its local engine now plays White.
6. Execute every announced move on the physical eboard. Neither engine starts
   its reply until the preceding move has been physically completed.

For another game, select **New Game** on the physical-board Picochess. It sends
New Game to the peer, displays `Please wait`, and then displays `Remote ready`
after both games have returned to the starting position. Press **Switch Sides**
again to let the local White engine start.

The mode stops on a New Game initiated independently on the remote instance,
connection loss, illegal protocol transition or position mismatch. Correct the
setup, start a new game on both instances and select Remote again.
