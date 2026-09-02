# Deadlocks in Operating Systems

A deadlock is a state in which a set of processes are each waiting for an
event that only another process in the set can cause. None of them can
proceed, and without intervention the system stays stuck indefinitely.

## The four Coffman conditions

Deadlock can arise only when all four of these hold simultaneously. Mutual
exclusion means at least one resource is held in a non-sharable mode. Hold
and wait means a process holding one resource is waiting to acquire others.
No preemption means a resource can be released only voluntarily by the
process holding it. Circular wait means there exists a set of waiting
processes such that each is waiting for a resource held by the next, and the
last is waiting for one held by the first.

Because all four are necessary, breaking any single one is enough to make
deadlock impossible. This is the basis of every prevention strategy.

## Prevention versus avoidance

Prevention attacks one of the four conditions structurally. Requiring a
process to request all its resources at once breaks hold and wait, but
wastes resources and can starve processes that need many. Imposing a global
ordering on resource types and requiring requests in increasing order breaks
circular wait, and is the technique most often used in practice because it
costs nothing at runtime.

Avoidance is different. It allows the four conditions but examines each
request before granting it, refusing any request that would move the system
into an unsafe state. The Banker's algorithm is the classic example: it
requires each process to declare its maximum demand in advance, then grants
a request only if some sequence of completions remains possible afterwards.
A safe state is not the same as a deadlock-free state, it is the stronger
guarantee that no future request pattern can force one.

## Detection and recovery

Some systems permit deadlock and detect it after the fact by periodically
searching the wait-for graph for a cycle. Recovery then means either
terminating processes or preempting resources, both of which are expensive
and can lose work. Databases commonly take this route because transactions
can be rolled back cleanly, whereas an operating system usually cannot undo
arbitrary process side effects.

The ostrich algorithm, ignoring the problem entirely, is a legitimate
engineering choice when deadlocks are rare and a reboot is cheaper than the
machinery required to prevent them. Most general-purpose kernels do exactly
this.
