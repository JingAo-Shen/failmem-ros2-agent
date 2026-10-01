| Run Name | Action Profile | Target Goal | Doorway Perception | Nav2 Status (Code) | Est. Nav2 Nav Time ($s$) | Assumed Settling ($s$) | Stability Window ($s$) | Total Sim Duration ($s$) | Physical Arrival Verified |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `H1_aligned_run1` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` (23 rays) | `SUCCEEDED` (4) | $13.4$ (est.) | $3.0$ (nom.) | $2.4$ | $18.8$ | **False** (excess av: 0.1068 > 0.08) |
| `H1_aligned_run2` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` (22 rays) | `SUCCEEDED` (4) | $13.4$ (est.) | $3.0$ (nom.) | $2.4$ | $18.8$ | **True** |
| `H1_oblique_run1` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` (23 rays) | `SUCCEEDED` (4) | $11.1$ (est.) | $3.0$ (nom.) | $2.3$ | $16.4$ | **True** |
| `H1_oblique_run2` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` (22 rays) | `SUCCEEDED` (4) | $11.0$ (est.) | $3.0$ (nom.) | $2.3$ | $16.3$ | **True** |
