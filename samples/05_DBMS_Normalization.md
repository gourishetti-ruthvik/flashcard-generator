# Database Normalization

Normalization organizes a relational schema to reduce redundancy and avoid
update anomalies. Each normal form is a stricter constraint than the last.

## Why redundancy is a correctness problem

Consider a table storing `(student_id, student_name, course, instructor)`.
If a student takes four courses, their name is stored four times. Change it
in three rows and forget the fourth, and the database now holds two
contradictory answers to "what is this student's name?" That is an update
anomaly, and it is a correctness bug, not merely a storage cost.

There are three classic anomalies:

- **Update anomaly** — the same fact stored in many rows drifts out of sync.
- **Insertion anomaly** — you cannot record a new instructor until at least
  one student enrolls in their course.
- **Deletion anomaly** — removing the last student on a course also destroys
  the fact that the instructor teaches it.

## The normal forms

**First normal form (1NF)** requires every attribute to hold a single
atomic value. A column containing "Maths, Physics, Chemistry" violates it.

**Second normal form (2NF)** requires 1NF plus no partial dependency: no
non-key attribute may depend on only part of a composite primary key. If the
key is `(student_id, course)` and `student_name` depends on `student_id`
alone, the table is not in 2NF.

**Third normal form (3NF)** requires 2NF plus no transitive dependency. If
`student_id` determines `department`, and `department` determines
`department_head`, then `department_head` depends on the key only
transitively and belongs in its own table.

**Boyce-Codd normal form (BCNF)** tightens 3NF: for every non-trivial
dependency X to Y, X must be a superkey. Every BCNF relation is in 3NF, but
not every 3NF relation is in BCNF.

## The trade-off nobody mentions in the definition

Higher normal forms mean more tables, and more tables mean more joins. A
schema in BCNF may need five joins to answer a query that a denormalized
table answers with a single scan. Analytical workloads, which read far more
than they write, routinely denormalize on purpose: the anomalies that
normalization prevents only matter when data is updated in place, and a
warehouse table that is written once and read a million times is not
exposed to them.

Normalize until it hurts, denormalize until it works.
