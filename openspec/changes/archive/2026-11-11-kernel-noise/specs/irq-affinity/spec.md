## ADDED Requirements

### Requirement: irq-affinity warns about irqbalance
When an `irqbalance` process is running, `irq-affinity` SHALL print one warning per
command that irqbalance will overwrite the affinities, and SHALL still run.

#### Scenario: irqbalance running
- **WHEN** `irq-affinity mask C8-15` runs while irqbalance is running
- **THEN** one warning naming irqbalance is printed, and the IRQ affinities are changed

#### Scenario: irqbalance not running
- **WHEN** no irqbalance process exists
- **THEN** no warning is printed
