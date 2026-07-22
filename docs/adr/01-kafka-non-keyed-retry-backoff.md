# Kafka Retry Backoff for Non-Keyed Topics

## 1. Context

`KafkaSubscriber`'s retry design (`_RetryMiddleware`, exponential backoff via
`NACK_ON_ERROR` plus an inline `asyncio.sleep`) blocks the whole poll loop for
that consumer while a message backs off. Every partition the consumer owns
stalls, not just the failing one.

For a keyed topic that is fine: a partition is already one logical ordered
stream, so blocking it while a message backs off does not hold up anything
that was not already serialized behind it.

For a non-keyed topic (no ordering requirement), the same partition carries
unrelated messages round-robined onto it. Blocking it delays those messages
for no ordering reason.

Four options were considered.

## 2. Options considered

### 2.1 Numbered retry topics

Java's `@RetryableTopic`, or the same idea as Rabbit's per-delay dead-letter
queues: give each backoff tier its own topic (`topic.5`, `topic.30`, ...).

Rejected. Kafka has no message TTL or broker-managed delayed delivery like
Rabbit's `x-message-ttl` plus DLX, so every tier still needs the same
in-process sleep this design already has. The only thing gained is isolating
the block to one topic. Rabbit's DLX queues are declared by the app at
runtime and expire themselves (`x-expires`); Kafka topics are
ops-provisioned (partitions, replication, retention, monitoring), so N new
topics per subscriber is real infrastructure work for a small isolation win.

### 2.2 External delay store plus poller

Ack the message immediately on failure, write `{payload, due_at, attempt}`
to Redis or a Mongo collection, and have a background poller republish it to
the original topic once due.

Rejected. Adds a second moving part (a poller, its own failure modes, its
own monitoring) for state the in-process fetch loop already tracks
(`_retry_state`). Too much for the size of the actual problem.

### 2.3 `max_workers` concurrency

FastStream's confluent broker supports running several handlers
concurrently off one shared semaphore, so unrelated messages on the same
partition could process while one backs off.

Rejected, for two independent reasons.

1. No partition affinity: dispatch is a flat semaphore with no per-partition
   reservation, so a single hot partition can consume every worker slot
   itself.
2. FastStream requires `ack_policy=ACK_FIRST` whenever `max_workers>1`
   (raises `SetupError` otherwise), committing the offset before the
   handler runs. That breaks the NACK-and-redeliver retry this whole design
   depends on. Moving the retry loop into the handler itself works
   mechanically, but the retry state then lives only in process memory: a
   crash mid-retry loses the message outright, since the offset is already
   committed and Kafka will not redeliver it. Confirmed against a real
   broker: a `SIGKILL` mid-retry loses the message.

### 2.4 Partition pause and resume

`confluent_kafka.Consumer.pause()` / `.resume()`: on failure, pause the
failing partition and schedule a background resume after the backoff delay,
instead of blocking the poll loop with `asyncio.sleep`.

Chosen. See Decision.

## 3. Decision

Use partition pause and resume, gated to messages with no Kafka key
(`raw_message.key() is None`). Keyed messages keep today's inline
`asyncio.sleep` unchanged: their partition is already a single ordered
stream, so blocking it costs nothing extra, and pausing it would add
complexity for no benefit.

For a non-keyed message: pause the specific `(topic, partition)`, keep
polling (other partitions the consumer owns keep flowing since the fetch
loop no longer awaits a sleep), and resume that partition once the backoff
delay elapses. The offset is never committed during this, so redelivery and
attempt counting are unchanged from today.

Verified against a real broker that `pause()` is purely client-side: a
`SIGKILL` mid-pause leaves nothing durable. A fresh consumer instance
assigned the same partition reads normally right away, no stuck state.

## 4. Consequences

- Unrelated messages on a non-keyed topic's other partitions no longer wait
  on one partition's backoff.
- Within the same partition, order is still strict FIFO: a backing-off
  message still blocks whatever is queued directly behind it on that
  partition. Kafka cannot skip a message and return to it later without
  external state (rejected in 2.2), so this is an accepted limit, not a bug.
- Pause and resume calls run through the same single-thread executor
  FastStream already uses to serialize all confluent-kafka client calls
  (the client is not thread-safe). This is why the call cannot just happen
  inline on the event loop.
- No ack-policy change, no new infrastructure, no loss of at-least-once
  delivery.
