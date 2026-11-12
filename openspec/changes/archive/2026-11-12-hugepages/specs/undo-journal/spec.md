## ADDED Requirements

### Requirement: An action that rolled itself back leaves no record
When an action fails after undoing its own changes, its undo record SHALL be removed from
the journal before the run stops, and the restore hint SHALL count only records that
remain.

#### Scenario: Rolled-back action
- **WHEN** a run with `-u j` records actions 1 and 2, and action 2 fails after rolling itself back
- **THEN** the journal holds only action 1's record, and `restore j` undoes only action 1

#### Scenario: Rolled back as the first change
- **WHEN** the rolled-back action is the first one that would have changed anything
- **THEN** the message says that nothing was changed, and no journal record exists for the run

### Requirement: Runs are serialized
A run SHALL hold an exclusive lock for its whole duration, including `restore`, and a
second run SHALL wait for it. `restore` SHALL read the journal again once it holds the
lock and replay what it finds then; a journal that existed when the command line was
checked but is gone by then SHALL count as already restored (message, exit status 0).

#### Scenario: Two hooks at once
- **WHEN** two VMs start at the same time and both run `hugepages 8`
- **THEN** the runs execute one after the other and the pool grows by 16

#### Scenario: Two restores of the same journal
- **WHEN** two `restore j` runs start at the same time
- **THEN** the first replays the journal and deletes it, and the second reports that `j` was already restored and exits 0 without replaying anything

#### Scenario: Record appended while waiting
- **WHEN** `restore j` waits for the lock while another run appends a record to `j`
- **THEN** the restore replays that record too
