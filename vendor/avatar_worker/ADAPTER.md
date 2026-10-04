# Avatar worker adapter v1

Source: Roleplay Avatar commit `32d3fa444b11a4a01bdda28befef8050581f31ab`, MIT.
Only the CPU contract/assets layer and the 2D creation stages are included.
`UPSTREAM.json` records the unmodified input hashes. The worker still validates
all eight character contracts and the source-lip-warp-v3 mouth binding.

Downstream modifications:

- `services/create_character.py` reads `AVATAR_WORK_ROOT` for job and published
  character directories. Code and models remain separately configured.
- `CreationStore.create` accepts a stable validated job ID and returns an
  existing job without submitting twice. Owner/request checks live in the host.
- The host wrapper selects the configured Linux local runner or GPUQ and supplies explicit environment paths.
- `web/src/avatar/puppet.js` uses the host-scoped asset base and disposes its RAF
  loop/WebGL context when unmounted. Actions and shaders retain the upstream math.

This adapter never launches a second conversation model. World engine replies
are the only dialogue source. Character assets/presentation errors do not change
committed world state. Native Cubism is a separate format, not generated here.

- Downstream lifecycle hardening recovers missing GPUQ receipts by the exact job
  directory, refuses unconfirmed retries, and treats atomically published packages
  as complete even if cancellation races with the final status write.
- The bootstrap accepts an older system Python before
  execing the explicitly configured project interpreter.
