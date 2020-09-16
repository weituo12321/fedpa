# coding=utf-8
# Copyright 2020 Maruan Al-Shedivat.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Utility functions for objective optimization."""

import functools
from typing import Callable

import jax.numpy as jnp
from jax import jit, lax, random, vmap

from ..objectives.base import StochasticObjective


@functools.partial(jit, static_argnums=(0, 1))
def _solve_sgd(
    learning_rate_schedule: Callable[[int], float],
    objective: StochasticObjective,
    steps: int,
    momentum: float,
    noise_scale: float,
    prng_key: jnp.ndarray,
    init_state: jnp.ndarray,
    init_momentum: jnp.ndarray,
):
    """Runs SGD on a stochastic objective for the specified number of steps."""

    @jit
    def _sgd_step(i, inputs):
        """Performs a single step of SGD."""
        x, v, x_avg, prng_key = inputs
        sg, prng_key = objective.grad(x, prng_key)
        sg_noise = noise_scale * random.normal(prng_key, sg.shape)
        sg = sg + sg_noise * jnp.sqrt(2.0 / learning_rate_schedule(i))
        v = momentum * v + sg
        x = x - learning_rate_schedule(i) * v
        x_avg = (x_avg * i + x) / (i + 1)
        return x, v, x_avg, prng_key

    init_state_avg = jnp.zeros_like(init_state, dtype=jnp.float32)
    inputs = (init_state, init_momentum, init_state_avg, prng_key)
    x, v, x_avg, _ = lax.fori_loop(0, steps, _sgd_step, inputs)
    return x, v, x_avg


def solve_sgd(
    objective: StochasticObjective,
    prng_key: jnp.ndarray,
    init_states: jnp.ndarray,
    init_momenta: jnp.ndarray,
    *,
    learning_rate_schedule: Callable[[int], float],
    steps: int,
    momentum: float = 0.0,
    noise_scale: float = 0.0,
):
    """Runs SGD on a stochastic objective for the specified number of steps.

    If multiple initial states and momenta provided, runs a solver for each
    of them in parallel using vectorization via `vmap`.

    While running SGD, additionally computes the running average of the iterates
    (i.e., the Polyak-Juditsky iterate averaging). Optionally, adds Gaussian
    noise to the stochastic gradients (useful for implementing SGLD sampling).

    Args:
        objective: An stochastic objective function.
        prng_key: A key for random number generation.
        init_states: The initial state vector.
        init_momenta: The initial momentum vector.
        steps: The number of stochastic gradient steps to use.
        learning_rate_schedule: A function that maps step to a learning rate.
        momentum: The momentum coefficient.
        noise_scale: The scale of the Gaussian noise added to the gradient.
            If non-zero, the noise is additionally scaled by `sqrt(2 / lr_i)`,
            such that if `noise_scale=1.` the algorithm produces SGLD iterates.

    Returns:
      A tuple of updated (state, momentum, state_avg) after SGD steps.
    """
    if init_states.ndim == 1:
        init_states = jnp.expand_dims(init_states, axis=0)
    if init_momenta.ndim == 1:
        init_momenta = jnp.expand_dims(init_momenta, axis=0)
    prng_keys = random.split(prng_key, init_states.shape[0])
    solver = functools.partial(
        _solve_sgd,
        learning_rate_schedule,
        objective,
        steps,
        momentum,
        noise_scale,
    )
    xs, vs, x_avgs = vmap(solver)(prng_keys, init_states, init_momenta)
    return jnp.squeeze(xs), jnp.squeeze(vs), jnp.squeeze(x_avgs)
