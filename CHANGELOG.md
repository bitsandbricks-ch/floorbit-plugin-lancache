# Changelog

Each release has a section `## <version>`; its text becomes the GitHub release notes and the
Marketplace's "what's new".

## 1.0.2

- Shows its own icon in Floorbit's plugin list and Marketplace.
- Stats from the agent with an odd `dns` part no longer fail; the numbers are kept, the DNS part is skipped.

## 1.0.1

- Keeps reading for the whole event when a round goes wrong. Something that isn't a web server at
  the cache address, or any other surprise, used to stop the reading until the agent restarted; now
  it is a warning and the next round runs as usual.
- Reads on past a log full of zeros (as after a crash) and past an edited positions file.
- The DNS check gives up after its timeout even when other answers keep arriving.

## 1.0.0

- First release from its own repository. Until now the plugin shipped inside Floorbit; it works
  the same, and the local agents get it as the same signed file.
