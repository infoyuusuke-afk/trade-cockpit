# Controller + Market Input Integration v1

This composition joins approved market-input failover to the Autonomy Controller.

A healthy selected source sets data health OK and permits the normal daily planning loop. Loss of all healthy sources degrades data and routes to self-healing. Source disagreement blocks data and routes SAFE recovery. A verified secondary source can keep the autonomous loop alive when the primary is unhealthy.

The integration remains side-effect free and cannot submit orders or publish.
