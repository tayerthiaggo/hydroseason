# Real-catchment spot check: where the candidate and baseline disagree

38 cycles where both algorithms produced the identical date are omitted below (nothing to adjudicate). This file lists only the 17 cycles where they disagree (one applied and the other abstained, or they chose different months), across the 5 development catchments plus Kakadu National Park (real DEA data, never inspected for this endpoint-refinement work). Catchment identity is kept in the span id -- if that's a source of bias for your review, ignore the prefix and read the values fresh. Decode key in `blind_check_all_key.json`.

---

### daly_river_nt_2008  (peak 2008-03 to peak 2009-02)

Monthly extent_pct: 2008-03=1.084, 2008-04=0.305, 2008-05=0.265, 2008-06=0.228, 2008-07=0.185, 2008-08=0.144, 2008-09=0.143, 2008-10=0.112, 2008-11=0.115, 2008-12=0.193, 2009-01=0.499, 2009-02=1.588

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2008-11 | 2008-10, 2008-11 | confirmed | accepted |
| **Algorithm B** | 2008-10 | 2008-10 | confirmed | accepted |

---

### daly_river_nt_2012  (peak 2012-03 to peak 2013-04)

Monthly extent_pct: 2012-03=1.099, 2012-04=0.272, 2012-05=0.154, 2012-06=0.251, 2012-07=0.224, 2012-08=0.191, 2012-09=0.154, 2012-10=0.191, 2012-11=0.125, 2012-12=0.154, 2013-01=0.168, 2013-02=0.334, 2013-03=0.243, 2013-04=0.416

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | — | 2012-11, 2012-12, 2013-01 | unresolved | unstable_quality_sensitivity |
| **Algorithm B** | 2013-02 | 2012-09, 2012-10, 2012-11, 2012-12, 2013-01, 2013-02 | provisional | low_quality_peak |

---

### daly_river_nt_2014  (peak 2014-02 to peak 2015-01)

Monthly extent_pct: 2014-02=0.555, 2014-03=0.279, 2014-04=0.164, 2014-05=0.195, 2014-06=0.199, 2014-07=0.186, 2014-08=0.160, 2014-09=0.140, 2014-10=0.127, 2014-11=0.133, 2014-12=0.163, 2015-01=0.648

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | — | 2014-10, 2014-11 | unresolved | unstable_quality_sensitivity |
| **Algorithm B** | 2014-12 | 2014-10, 2014-11, 2014-12 | provisional | essential_low_quality_recovery |

---

### daly_river_nt_2015  (peak 2015-01 to peak 2016-01)

Monthly extent_pct: 2015-01=0.648, 2015-02=0.287, 2015-03=0.210, 2015-04=0.215, 2015-05=0.187, 2015-06=0.170, 2015-07=0.164, 2015-08=0.149, 2015-09=0.137, 2015-10=0.129, 2015-11=0.131, 2015-12=0.334, 2016-01=0.564

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2015-10 | 2015-10 | confirmed | accepted |
| **Algorithm B** | 2015-11 | 2015-11 | confirmed | accepted |

---

### daly_river_nt_2019  (peak 2019-04 to peak 2020-01)

Monthly extent_pct: 2019-04=0.194, 2019-05=0.155, 2019-06=0.162, 2019-07=0.147, 2019-08=0.136, 2019-09=0.135, 2019-10=0.125, 2019-11=0.117, 2019-12=0.118, 2020-01=0.512

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2019-12 | 2019-12 | provisional | interval_peak |
| **Algorithm B** | 2019-11 | 2019-11 | provisional | interval_peak |

---

### fitzroy_river_wa_2006  (peak 2006-01 to peak 2007-03)

Monthly extent_pct: 2006-01=0.703, 2006-02=0.276, 2006-03=0.610, 2006-04=0.132, 2006-05=0.089, 2006-06=0.068, 2006-07=0.055, 2006-08=0.046, 2006-09=0.033, 2006-10=0.019, 2006-11=0.026, 2006-12=0.027, 2007-01=0.127, 2007-02=0.098, 2007-03=0.286

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2006-12 | 2006-12 | provisional | low_quality_peak |
| **Algorithm B** | 2006-10 | 2006-10 | provisional | low_quality_peak |

---

### fitzroy_river_wa_2008  (peak 2008-02 to peak 2009-02)

Monthly extent_pct: 2008-02=0.275, 2008-03=0.202, 2008-04=0.136, 2008-05=0.078, 2008-06=0.100, 2008-07=0.056, 2008-08=0.039, 2008-09=0.037, 2008-10=0.028, 2008-11=0.025, 2008-12=0.039, 2009-01=0.200, 2009-02=1.168

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2008-11 | 2008-11 | provisional | low_quality_peak |
| **Algorithm B** | 2008-12 | 2008-11, 2008-12 | provisional | low_quality_peak |

---

### fitzroy_river_wa_2015  (peak 2015-01 to peak 2016-02)

Monthly extent_pct: 2015-01=0.318, 2015-02=0.215, 2015-03=0.164, 2015-04=0.100, 2015-05=0.080, 2015-06=0.070, 2015-07=0.045, 2015-08=0.046, 2015-09=0.038, 2015-10=0.034, 2015-11=0.034, 2015-12=0.045, 2016-01=0.079, 2016-02=0.132

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2015-10 | 2015-10 | provisional | interval_peak |
| **Algorithm B** | 2015-12 | 2015-11, 2015-12 | provisional | interval_peak |

---

### fitzroy_river_wa_2018  (peak 2018-02 to peak 2019-02)

Monthly extent_pct: 2018-02=0.735, 2018-03=0.222, 2018-04=0.159, 2018-05=0.105, 2018-06=0.095, 2018-07=0.079, 2018-08=0.062, 2018-09=0.053, 2018-10=0.041, 2018-11=0.035, 2018-12=0.037, 2019-01=0.073, 2019-02=0.088

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2018-12 | 2018-12 | confirmed | accepted |
| **Algorithm B** | 2018-11 | 2018-11 | confirmed | accepted |

---

### fitzroy_river_wa_2020  (peak 2020-03 to peak 2021-03)

Monthly extent_pct: 2020-03=0.381, 2020-04=0.173, 2020-05=0.108, 2020-06=0.100, 2020-07=0.072, 2020-08=0.064, 2020-09=0.047, 2020-10=0.035, 2020-11=0.049, 2020-12=0.403, 2021-01=0.249, 2021-02=0.993, 2021-03=1.020

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2020-10 | 2020-10 | confirmed | accepted |
| **Algorithm B** | 2020-11 | 2020-10, 2020-11 | confirmed | accepted |

---

### fitzroy_river_wa_2021  (peak 2021-03 to peak 2022-02)

Monthly extent_pct: 2021-03=1.020, 2021-04=0.253, 2021-05=0.147, 2021-06=0.109, 2021-07=0.101, 2021-08=0.077, 2021-09=0.058, 2021-10=0.046, 2021-11=0.053, 2021-12=0.047, 2022-01=0.066, 2022-02=0.555

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2021-12 | 2021-12, 2022-01 | confirmed | accepted |
| **Algorithm B** | 2021-10 | 2021-10 | confirmed | accepted |

---

### gilbert_river_qld_2005  (peak 2005-01 to peak 2006-02)

Monthly extent_pct: 2005-01=1.634, 2005-02=0.508, 2005-03=0.199, 2005-04=0.156, 2005-05=0.153, 2005-06=0.153, 2005-07=0.132, 2005-08=0.126, 2005-09=0.116, 2005-10=0.105, 2005-11=0.096, 2005-12=0.144, 2006-01=0.130, 2006-02=0.782

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2005-12 | 2005-11, 2005-12 | provisional | essential_low_quality_recovery |
| **Algorithm B** | — | 2005-11 | unresolved | unstable_quality_sensitivity |

---

### gilbert_river_qld_2009  (peak 2009-01 to peak 2010-02)

Monthly extent_pct: 2009-01=7.619, 2009-02=4.583, 2009-03=0.444, 2009-04=0.249, 2009-05=0.197, 2009-06=0.182, 2009-07=0.178, 2009-08=0.171, 2009-09=0.139, 2009-10=0.116, 2009-11=0.113, 2009-12=0.130, 2010-01=1.566, 2010-02=2.846

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2009-12 | 2009-11, 2009-12 | provisional | low_quality_peak |
| **Algorithm B** | 2009-11 | 2009-11 | provisional | low_quality_peak |

---

### gilbert_river_qld_2019  (peak 2019-02 to peak 2020-02)

Monthly extent_pct: 2019-02=0.771, 2019-03=0.328, 2019-04=0.238, 2019-05=0.197, 2019-06=0.169, 2019-07=0.169, 2019-08=0.148, 2019-09=0.140, 2019-10=0.118, 2019-11=0.105, 2019-12=0.116, 2020-01=0.396, 2020-02=2.071

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2019-11 | 2019-11 | confirmed | accepted |
| **Algorithm B** | 2019-12 | 2019-11, 2019-12 | confirmed | accepted |

---

### gilbert_river_qld_2020  (peak 2020-02 to peak 2021-01)

Monthly extent_pct: 2020-02=2.071, 2020-03=0.314, 2020-04=0.213, 2020-05=0.168, 2020-06=0.179, 2020-07=0.162, 2020-08=0.160, 2020-09=0.139, 2020-10=0.121, 2020-11=0.122, 2020-12=0.174, 2021-01=8.291

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | 2020-10 | 2020-10 | confirmed | accepted |
| **Algorithm B** | 2020-11 | 2020-11 | confirmed | accepted |

---

### kakadu_national_park_2021  (peak 2021-02 to peak 2022-01)

Monthly extent_pct: 2021-02=15.846, 2021-03=8.031, 2021-04=6.494, 2021-05=5.136, 2021-06=5.087, 2021-07=5.424, 2021-08=5.428, 2021-09=5.208, 2021-10=5.032, 2021-11=5.137, 2021-12=9.103, 2022-01=20.343

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | — | 2021-05, 2021-06, 2021-07, 2021-08, 2021-09, 2021-10, 2021-11 | unresolved | unstable_quality_sensitivity |
| **Algorithm B** | 2021-10 | 2021-10 | provisional | low_quality_peak |

---

### kakadu_national_park_2024  (peak 2024-03 to peak 2025-03)

Monthly extent_pct: 2024-03=14.105, 2024-04=8.477, 2024-05=6.080, 2024-06=6.379, 2024-07=6.250, 2024-08=6.101, 2024-09=5.738, 2024-10=5.262, 2024-11=5.167, 2024-12=7.836, 2025-01=9.638, 2025-02=9.705, 2025-03=10.290

| | final low-state month | support set | status | reason |
| --- | --- | --- | --- | --- |
| **Algorithm A** | — | 2024-10, 2024-11 | unresolved | unstable_quality_sensitivity |
| **Algorithm B** | 2024-12 | 2024-11, 2024-12 | provisional | interval_peak |
