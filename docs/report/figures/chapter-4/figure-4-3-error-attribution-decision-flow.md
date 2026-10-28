# Figure 4.3. Stage-Based Error-Attribution Decision Flow

```text
Does the required information exist in the declared store?
        ├── No  → Storage omission or distortion
        └── Yes
              ↓
Was it reached by the retrieval process?
        ├── No  → Retrieval failure
        └── Yes
              ↓
Did it survive selection, fusion, and the evidence budget?
        ├── No  → Packaging or budget loss
        └── Yes
              ↓
Was the final EvidenceBundle sufficient?
        ├── No  → Incomplete evidence
        └── Yes
              ↓
Did the Answerer use it correctly?
        ├── No  → Answerer utilisation failure
        └── Yes
              ↓
Do token and semantic scores disagree?
        ├── Yes → Evaluation disagreement review
        └── No  → Mixed / indeterminate review
```
