"""Orkestratör: her DMA'da akıllı depoların ne zaman ve ne hızla dolacağına karar verir.

Her DMA için bir karesel program çözülür (günün her adımı için, düğüm başına bir dolum profili):

    en aza indir   Σ_t (Q(t)/Q̄)² + w · Σ_t fiyat_oranı(t) · Q(t)/Q̄
    kısıtlar       V(t) = V0 + Δt · Σ_{s≤t} (q(s) − c(s))       depo kütle dengesi
                   yedek · Vmax ≤ V(t) ≤ Vmax                   deprem ve kesinti yedeği
                   0 ≤ q(t) ≤ giriş kapasitesi
                   V(gün sonu) = V0                              gün sonunda aynı doluluk

Q(t) DMA girişinden geçen toplam debidir (akıllı dolumlar + kontrol edilemeyen talep + kaçak).
İlk terim girişi düzleştirir, ikinci terim dolumu pahalı puant saatlerinden ucuz gece saatlerine kaydırır.
"""
from __future__ import annotations

from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from .config import PRICE_WEIGHT, RESERVE_FRACTION
from .tanks import NodeStorage


@dataclass
class Plan:
    inflow: np.ndarray   # [n, T] akıllı depolara şebekeden giren debi (m³/sa)
    level: np.ndarray    # [n, T+1] depo hacmi, adım başları ve gün sonu (m³)
    status: dict         # DMA adı -> çözücü durumu


def float_valve_plan(storage: NodeStorage) -> Plan:
    """Yapay zekâ kapalı: şamandıralı vana depoyu hep dolu tutar, giriş = tüketim."""
    T = storage.consumption.shape[1]
    level = np.repeat(storage.volume[:, None], T + 1, axis=1)
    return Plan(inflow=storage.consumption.copy(), level=level, status={})


def orchestrate(storage: NodeStorage, dma_members: dict[str, list[str]], uncontrolled: dict[str, np.ndarray],
                price_rel: np.ndarray, reserve: float = RESERVE_FRACTION, price_weight: float = PRICE_WEIGHT,
                log=print) -> Plan:
    """Her DMA için dolum planını çözer. `uncontrolled` DMA başına kontrol edilemeyen debi (m³/sa, [T])."""
    idx = storage.index()
    T = storage.consumption.shape[1]
    dt = 24.0 / T
    ones = np.ones((1, T))
    inflow = storage.consumption.copy()
    level = np.repeat(storage.volume[:, None], T + 1, axis=1)
    status = {}
    for dma, members in dma_members.items():
        rows = [idx[j] for j in members if j in idx]
        if not rows:
            continue
        c = storage.consumption[rows]
        vmax = storage.volume[rows]
        vmin = reserve * vmax
        qmax = np.maximum(storage.inlet_max[rows], c.max(axis=1) * 1.01)
        U = uncontrolled.get(dma, np.zeros(T))
        k = len(rows)

        q = cp.Variable((k, T), nonneg=True)
        v0 = cp.Variable(k)
        V = cp.reshape(v0, (k, 1), order="C") @ ones + dt * cp.cumsum(q - c, axis=1)
        Q = cp.sum(q, axis=0) + U
        q_bar = (c.sum() + U.sum()) / T
        scale = np.maximum(c.mean(axis=1, keepdims=True), 1e-6)
        objective = (cp.sum_squares(Q / q_bar) * (24.0 / T)
                     + price_weight * (price_rel @ Q) / q_bar * (24.0 / T)
                     + 1e-3 * cp.sum_squares(cp.multiply(q, 1.0 / scale)) / (k * T / 24.0))
        constraints = [
            q <= qmax[:, None] @ ones,
            V >= vmin[:, None] @ ones,
            V <= vmax[:, None] @ ones,
            V[:, T - 1] == v0,
            v0 >= vmin, v0 <= vmax,
        ]
        prob = cp.Problem(cp.Minimize(objective), constraints)
        try:
            prob.solve(solver=cp.CLARABEL)
        except cp.SolverError:
            prob.solve(solver=cp.OSQP, max_iter=20000)
        status[dma] = prob.status
        if prob.status not in ("optimal", "optimal_inaccurate") or q.value is None:
            log(f"  {dma}: çözüm bulunamadı ({prob.status}), şamandıra davranışı korunuyor")
            continue
        qv = np.clip(q.value, 0.0, None)
        inflow[rows] = qv
        level[rows, 0] = v0.value
        level[rows, 1:] = v0.value[:, None] + dt * np.cumsum(qv - c, axis=1)
    level = np.clip(level, 0.0, storage.volume[:, None])
    bad = [d for d, s in status.items() if s not in ("optimal", "optimal_inaccurate")]
    log(f"  orkestratör: {len(status)} DMA çözüldü, {len(bad)} başarısız")
    return Plan(inflow=inflow, level=level, status=status)
