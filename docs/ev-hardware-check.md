# Manual EV hardware check (issue #56)

No physical write has been performed as part of implementation. Record the
original node configuration before testing. The candidate is CANMIO node 258
(`0102`), event `0:1000` (`0000:03E8`), EV2, reported original value 12 (`0C`).
Reconfirm that value from hardware. Choose the safe test value together before
sending EVLRN; this document does not choose one.

These full GridConnect commands assume the configured PC CAN ID is 126
(header `BFC0`). For another PC ID the header is `(0x580 | can_id) << 5`.
`VV` below is the agreed byte value in **two hexadecimal digits**. Do not send
literal placeholders. Reply headers depend on the node's live CAN ID; the
payloads below identify expected replies. Only one node may be in learn mode;
do not run another teaching/configuration utility concurrently.

| Step | Frame to send | Required result before proceeding |
| --- | --- | --- |
| Confirm capacity and flags | `:SBFC0N73010205;`, `:SBFC0N73010208;` | PARAN `9B010205cc`, `9B010208ff`; capacity at least 2, flags identify FLiM consumer |
| Record identities | `:SBFC0N580102;`, then `:SBFC0N570102;` | NUMEV count; collect that many ENRSP identities/indices; confirm `0000:03E8` exists |
| Enter learn | `:SBFC0N530102;` | No acknowledgement is specified for NNLRN |
| Check learn flag, if parameter 8 was discovered | `:SBFC0N73010208;` | Bit `20` set establishes flag reporting. VLCB or previously observed reporting requires it set. A legacy clear bit is inconclusive; use write acknowledgement/readback below |
| Reconfirm original EV2 | `:SBFC0NB2000003E802;` | `D3000003E8020C`, from node 258's confirmed CAN ID |
| Write chosen value | `:SBFC0ND2000003E802VV;` | WRACK `590102`; stop on CMDERR `6F0102ee` or timeout |
| Verify chosen value | `:SBFC0NB2000003E802;` | `D3000003E802VV`, same sender and identity; compare the byte |
| Exit learn (also on failure) | `:SBFC0N540102;` | No acknowledgement is specified for NNULN |
| Confirm exit, if reliable flag reporting was established | `:SBFC0N73010208;` | `9B010208ff` with bit `20` clear; without reliable reporting exit remains unconfirmed |
| Rediscover | `:SBFC0N580102;`, then `:SBFC0N570102;` | Fresh count/identities, including any changed table indices |

The learn flag is proposed, not universally required, in CBUS Guide 6c. VLCB
Event Teach specifies it. If the legacy node never reports it set, NNLRN is only
a request: a matching WRACK plus EVANS verifies teaching. Always send NNULN,
and record the lack of exit confirmation in TRACE logs. Successful transmission
and complete rediscovery should show “Node 258: Changes saved successfully.” Do not use a clear legacy bit as proof of normal mode. If parameter 8 was
not discovered, omit its queries entirely; never continue after a failed query.

Then reread EVs through the existing discovery: for each freshly discovered
internal index `II` and supported EV `EE`, send `:SBFC0N9C0102IIEE;` and match
`B50102IIEEvv`. Do not reuse pre-write indices. Check the Events tab displays
confirmed results and its notification completes. A discovery failure must say
changes were saved but the displayed configuration may be incomplete.

To restore the original EV2, repeat enter/confirm, send the **exact restore** frame
`:SBFC0ND2000003E8020C;`, wait for `590102`, send
`:SBFC0NB2000003E802;` and require `D3000003E8020C`. Exit with
`:SBFC0N540102;`, confirm using `:SBFC0N73010208;` where reliable flag reporting
was established (otherwise record exit as unconfirmed), then rediscover and compare
with the recorded original configuration. EV dependencies may change other EVs;
review the complete refreshed configuration, not just EV2.

If any write fails, do not continue teaching. Attempt exit and check the learn
flag. If disconnected, exit cannot be confirmed: inspect the node before another
Save. Record Diagnostics/TRACE for entry, write, acknowledgement, readback, exit,
refresh and restoration. Verify Cancel emits no teaching frames in a separate
editing attempt.

References: [MERG Developer's Guide 6b](https://www.merg.org.uk/merg_wiki/lib/exe/fetch.php?media=public%3Acbuspublic%3Adeveloper_6b.pdf)
and [VLCB Event Teach / Opcode specifications](https://github.com/Versatile-LCB/VLCB-documents).
