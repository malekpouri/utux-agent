# Worked example of one gold item

Save as `docs/eval/example-item.md`. Everything here is synthetic: Method
Alpha, Method Beta, SynthImg and the source text are invented. The item uses
the reserved ids G9100, a90, a91 and a92 and must never enter a release.

The final JSON at the end validates against `utux.evalkit.gold.GoldItem`;
a test checks this.

## 1. What the item builder prepares

The item builder (not an annotator) picks a citing sentence and stores the
text of the source it cites, with its licence record.

**Text unit**

> Method Alpha reduces classification error compared with Method Beta on SynthImg [1], and it is twice as fast at inference [1].

**Source [1]**, `synthetic:alpha-2026`, abstract only, extraction quality `clean`

> We introduce Method Alpha, a lightweight image classifier. On the SynthImg benchmark, Method Alpha reduces top-1 error from 12.4% to 10.9% relative to Method Beta. Inference is 1.4 times faster than Method Beta on the same hardware. Results on other benchmarks are left to future work.

Origin is `natural`: the sentence was not edited. Domain `ml`, split `dev`,
no hard case.

## 2. Phase 1: claim extraction

Each annotator lists the claims alone.

| Annotator | Claims listed |
| --- | --- |
| a90 | (1) Method Alpha reduces classification error compared with Method Beta on SynthImg. (2) Method Alpha is twice as fast as Method Beta at inference. |
| a91 | (1) Method Alpha reduces classification error compared with Method Beta on SynthImg and is twice as fast at inference. |

a91 kept two assertions in one claim, against section 4.2 of the guideline:
one part can be true while the other is false. The adjudicator a92 fixes the
reference list as a90's two claims. `claim_extraction.adjudicated` is true,
and both raw lists are kept.

## 3. Phase 2: labelling the fixed claims

**Claim c1**, kind `finding`: Method Alpha reduces classification error compared with Method Beta on SynthImg.

| | a90 | a91 | Reference |
| --- | --- | --- | --- |
| Evidence span | "On the SynthImg benchmark ... relative to Method Beta." | same | same |
| Agreement label | `entails` | `entails` | `entails` |
| Scope flags | none | none | none |
| Status | `verified` | `verified` | `verified` |
| Expert would review | no | no | no |

"Top-1 error" is a classification error, so the claim follows directly.
The annotators agree; nothing is adjudicated.

**Claim c2**, kind `quantitative`: Method Alpha is twice as fast as Method Beta at inference.

| | a90 | a91 | Reference |
| --- | --- | --- | --- |
| Evidence span | "Inference is 1.4 times faster than Method Beta on the same hardware." | same | same |
| Agreement label | `contradicts` | `partial` | `contradicts` |
| Scope flags | `magnitude_mismatch` | `magnitude_mismatch` | `magnitude_mismatch` |
| Status | `contradicted` | `partially_supported` | `contradicted` |
| Expert would review | no | yes | no |

a91 read "faster" as partly supported. The guideline's table in section 5.3
maps `magnitude_mismatch` to `contradicts`: "twice as fast" cannot be true if
the source measured 1.4 times. The adjudicator sets `contradicts`, so the
status rules of section 5.4 give `contradicted`, and records why. The pair
and the claim are both marked `adjudicated`.

## 4. The stored gold item

In a release this is one line of a JSON Lines file. Shown here with
indentation.

```json
{
  "schema_version": 1,
  "item_id": "G9100",
  "gold_version": "0.0",
  "split": "dev",
  "domain": "ml",
  "origin": "natural",
  "hard_case": null,
  "text_unit": "Method Alpha reduces classification error compared with Method Beta on SynthImg [1], and it is twice as fast at inference [1].",
  "claims": [
    {
      "claim_id": "G9100-c1",
      "text": "Method Alpha reduces classification error compared with Method Beta on SynthImg.",
      "span": [
        0,
        79
      ],
      "kind": "finding",
      "pairs": [
        {
          "pair_id": "G9100-c1-s1",
          "source_id": "synthetic:alpha-2026",
          "source_group": "sg-synthetic-alpha",
          "text_hash": "sha256:50196adb5b83b4afe64b45fb8b6eeea4549afca6a8fdc37a5b2d88370b3d5813",
          "checked_text": "abstract",
          "extraction_quality": "clean",
          "evidence_spans": [
            {
              "passage_id": "p001",
              "offsets": [
                59,
                163
              ]
            }
          ],
          "agreement_label": "entails",
          "scope_flags": [],
          "raw": {
            "a90": {
              "evidence_spans": [
                {
                  "passage_id": "p001",
                  "offsets": [
                    59,
                    163
                  ]
                }
              ],
              "agreement_label": "entails",
              "scope_flags": [],
              "note": null
            },
            "a91": {
              "evidence_spans": [
                {
                  "passage_id": "p001",
                  "offsets": [
                    59,
                    163
                  ]
                }
              ],
              "agreement_label": "entails",
              "scope_flags": [],
              "note": null
            }
          },
          "adjudicated": false,
          "adjudication_reason": null
        }
      ],
      "status": "verified",
      "expert_would_review": false,
      "raw": {
        "a90": {
          "status": "verified",
          "expert_would_review": false,
          "note": null
        },
        "a91": {
          "status": "verified",
          "expert_would_review": false,
          "note": null
        }
      },
      "adjudicated": false,
      "adjudication_reason": null,
      "ambiguous": false
    },
    {
      "claim_id": "G9100-c2",
      "text": "Method Alpha is twice as fast as Method Beta at inference.",
      "span": [
        85,
        121
      ],
      "kind": "quantitative",
      "pairs": [
        {
          "pair_id": "G9100-c2-s1",
          "source_id": "synthetic:alpha-2026",
          "source_group": "sg-synthetic-alpha",
          "text_hash": "sha256:50196adb5b83b4afe64b45fb8b6eeea4549afca6a8fdc37a5b2d88370b3d5813",
          "checked_text": "abstract",
          "extraction_quality": "clean",
          "evidence_spans": [
            {
              "passage_id": "p001",
              "offsets": [
                164,
                232
              ]
            }
          ],
          "agreement_label": "contradicts",
          "scope_flags": [
            "magnitude_mismatch"
          ],
          "raw": {
            "a90": {
              "evidence_spans": [
                {
                  "passage_id": "p001",
                  "offsets": [
                    164,
                    232
                  ]
                }
              ],
              "agreement_label": "contradicts",
              "scope_flags": [
                "magnitude_mismatch"
              ],
              "note": null
            },
            "a91": {
              "evidence_spans": [
                {
                  "passage_id": "p001",
                  "offsets": [
                    164,
                    232
                  ]
                }
              ],
              "agreement_label": "partial",
              "scope_flags": [
                "magnitude_mismatch"
              ],
              "note": null
            }
          },
          "adjudicated": true,
          "adjudication_reason": "The guideline maps magnitude_mismatch to contradicts (section 5.3): twice as fast cannot be true if the source measured 1.4 times."
        }
      ],
      "status": "contradicted",
      "expert_would_review": false,
      "raw": {
        "a90": {
          "status": "contradicted",
          "expert_would_review": false,
          "note": null
        },
        "a91": {
          "status": "partially_supported",
          "expert_would_review": true,
          "note": null
        }
      },
      "adjudicated": true,
      "adjudication_reason": "The guideline maps magnitude_mismatch to contradicts (section 5.3): twice as fast cannot be true if the source measured 1.4 times.",
      "ambiguous": false
    }
  ],
  "annotation": {
    "annotators": [
      "a90",
      "a91"
    ],
    "adjudicator": "a92",
    "claim_extraction": {
      "raw": {
        "a90": [
          {
            "span": [
              0,
              79
            ],
            "text": "Method Alpha reduces classification error compared with Method Beta on SynthImg."
          },
          {
            "span": [
              85,
              121
            ],
            "text": "Method Alpha is twice as fast as Method Beta at inference."
          }
        ],
        "a91": [
          {
            "span": [
              0,
              121
            ],
            "text": "Method Alpha reduces classification error compared with Method Beta on SynthImg and is twice as fast at inference."
          }
        ]
      },
      "adjudicated": true,
      "adjudication_reason": "a91 kept two assertions in one claim, against section 4.2 of the guideline; the reference list is a90's two claims."
    }
  }
}
```

The offsets point into the stored source text; its SHA-256 is the
`text_hash`. Claim c2's span `[85, 121]` covers "and it is twice as fast at
inference" in the text unit.
