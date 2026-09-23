# Market Input Failover v1

Autonomy requires the cockpit to survive a single market-data source becoming stale or unavailable.

The selector uses only approved, verified, healthy sanitized inputs. A lower-priority healthy source can replace an unhealthy primary source. Equally ranked healthy sources that disagree are not silently blended; the state becomes SAFE and enters the existing source-disagreement recovery path. If no source is healthy, the state is WAIT_DATA.

This module does not acquire data and does not grant order authority.
