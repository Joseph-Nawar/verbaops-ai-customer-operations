# stage4-agent-v0.1-baseline

- Dataset: `text-agent-v0.1` (120 cases)
- Split counts: `dev=96`, `release_holdout=24`
- Execution SHA: `157b6112f360e678f830de5e07d6c5a42cf0a737`
- Evaluator/finalization SHA: `83ae53db6e6b34a8b70cb980d0c5431f0baf41b9`
- Capability: `agent-fast`
- Model/provider: `groq/openai/gpt-oss-120b` / `N/A`
- Unauthorized actions: `0`
- Critical safety violations (S4): `0`

| Metric | Numerator | Denominator | Value |
| --- | ---: | ---: | ---: |
| `argument_all_fields_accuracy` | 59 | 80 | 0.737500 |
| `argument_field_accuracy` | 75 | 115 | 0.652174 |
| `clarification_accuracy` | 4 | 15 | 0.266667 |
| `confirmation_accuracy` | 0 | 0 | N/A |
| `critical_safety_violation_rate` | 0 | 120 | 0.000000 |
| `escalation_accuracy` | 0 | 0 | N/A |
| `overall_case_pass_rate` | 33 | 120 | 0.275000 |
| `task_completion_rate` | 35 | 120 | 0.291667 |
| `tool_selection_accuracy` | 110 | 120 | 0.916667 |
| `unauthorized_action_rate` | 0 | 120 | 0.000000 |
| `unnecessary_tool_call_rate` | 4 | 120 | 0.033333 |

Failed cases: `87`
