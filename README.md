# OSDP for Home Assistant

A custom integration that turns Home Assistant into an
[OSDP](https://www.securityindustry.org/industry-standards/open-supervised-device-protocol/)
control panel. It talks to OSDP card readers over an RS-485 adapter (via
[libosdp](https://github.com/goToMain/libosdp)), so card scans and key presses
can drive automations and readers can show the result with their LED, buzzer
and outputs.

## Installation

Requires Home Assistant 2026.8 or newer.

1. In HACS, add this repository as a custom repository (category *Integration*)
   and install **OSDP**. Alternatively, copy `custom_components/osdp` into your
   Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → OSDP**.

## Setup

**Controller (one per RS-485 bus):** pick the serial adapter and the baud rate the
readers use. Paths under `/dev/serial/by-id/` are listed first: unlike
`/dev/ttyUSB0`, they don't change after a reboot. You can also type a path. To
change the port or baud rate later, use **Reconfigure** on the integration entry.

**Readers:** open **Configure** on the integration entry:

- **Add a reader:** the reader's OSDP address (0–126), a name, and optionally a
  Secure Channel key (SCBK, 32 hex characters). With a key set, communication
  is encrypted and the secure channel is enforced.
- **Edit a reader:** rename it, or change or clear its key.
- **Remove readers:** pick one or more. You can also delete a reader from its device page.
- **Settings:** optionally choose a user that scans are attributed to (shown
  in the logbook and on tags).

Changes apply immediately; there's no need to restart Home Assistant.

## What you get

Per reader:

| Entity | Description |
| --- | --- |
| `event.<reader>_card` | Fires `card_read` with the `tag_id` attribute. |
| `event.<reader>_keypad` | Fires `keypress` with the `keys` attribute (`*` and `#` included). Disabled by default; enable it for readers with a keypad. |
| `binary_sensor.<reader>_online` | Whether the reader answers polls. |
| `binary_sensor.<reader>_secure_channel` | Whether the encrypted Secure Channel is active. |

Vendor, model, serial number and firmware version reported by the reader are
shown on its device page once it comes online.

Per controller: `binary_sensor.<controller>_serial_connection` (adapter present)
and `sensor.<controller>_readers_online`. If the adapter is unplugged, the
integration keeps retrying and resumes on its own when it comes back.

Card scans are also passed to Home Assistant's **Tags**, so *Tag scanned*
triggers work. The device trigger *Tag scanned* / *Key pressed* and the
`osdp_event` bus event are still available.

## Actions

| Action | Use |
| --- | --- |
| `osdp.set_led` | Set the LED color, steady or blinking; with `duration` it returns to the previous state afterwards. |
| `osdp.beep` | Sound the buzzer (`on_time`, `off_time`, `repeat`). |
| `osdp.set_output` | Switch a reader output (e.g. a door strike), optionally for a `duration`. |

Durations are limited to 25.5 s by the protocol encoding.

Example: grant access for a known tag.

```yaml
automation:
  - alias: Front door access
    triggers:
      - trigger: state
        entity_id: event.front_door_card
    variables:
      reader: "{{ device_id('event.front_door_card') }}"
    actions:
      - if:
          - condition: template
            value_template: "{{ trigger.to_state.attributes.tag_id in ['123456', '654321'] }}"
        then:
          - action: osdp.set_led
            data: { device_id: "{{ reader }}", color: green, duration: 3 }
          - action: osdp.set_output
            data: { device_id: "{{ reader }}", state: true, duration: 5 }
        else:
          - action: osdp.set_led
            data: { device_id: "{{ reader }}", color: red, duration: 2 }
          - action: osdp.beep
            data: { device_id: "{{ reader }}", repeat: 3, on_time: 200, off_time: 200 }
```

## Troubleshooting

- Enable debug logging for `custom_components.osdp` to see every reader event.
  This also raises libosdp's own log level.
- **Download diagnostics** from the integration entry shows port state, online
  readers and reported identities, with keys redacted.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## License

MIT, see [LICENSE](LICENSE).
