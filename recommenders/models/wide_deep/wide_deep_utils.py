# Copyright (c) Recommenders contributors.
# Licensed under the MIT License.
from typing import Tuple, Dict, Optional
from dataclasses import dataclass, field

import torch
from torch.utils.data import DataLoader
from torch import nn

from recommenders.utils.constants import DEFAULT_USER_COL, DEFAULT_ITEM_COL

@dataclass(kw_only=True, frozen=True)
class WideAndDeepHyperParams:
    user_dim: int = 32
    item_dim: int = 32
    crossed_feat_dim: int = 1000
    dnn_hidden_units: Tuple[int, ...] = (128, 128)
    dnn_dropout: float = 0.0
    dnn_additional_embeddings_sizes: dict[str, Tuple[int, int]] = field(default_factory=dict)
    dnn_cont_features: int = 0

class WideAndDeepModel(nn.Module):
    def __init__(
        self, 
        num_users: int, 
        num_items: int, 
        hparams: WideAndDeepHyperParams = WideAndDeepHyperParams(),
    ):
        super().__init__()

        self.hparams = hparams
        self.n_users = num_users
        self.n_items = num_items
        
        self.users_emb = nn.Embedding(num_users, hparams.user_dim)
        self.items_emb = nn.Embedding(num_items, hparams.item_dim)
        self.additional_embs = nn.ModuleDict({
            k: nn.Embedding(num, dim) for k, (num, dim) in hparams.dnn_additional_embeddings_sizes.items()
        })

        # Randomly initialize embeddings
        total_emb_dim = hparams.user_dim + hparams.item_dim
        for _, emb in self.additional_embs.items():
            total_emb_dim += emb.embedding_dim
            nn.init.uniform_(emb.weight, -1, 1)

        layers = []
        prev_output = hparams.dnn_cont_features + total_emb_dim
        for hu in hparams.dnn_hidden_units:
            layers.append(nn.Linear(prev_output, hu))
            layers.append(nn.Dropout(hparams.dnn_dropout))
            layers.append(nn.ReLU())
            prev_output = hu

        self.deep = nn.Sequential(*layers)

        # Cross product of users-items
        exclusive_wide_input = hparams.crossed_feat_dim

        self.head = nn.Sequential(
            # Output is binary score. 1 iif item-user pair is a good recommendation.
            nn.Linear(exclusive_wide_input+prev_output, 1),
            nn.Sigmoid(),
        )

    def forward(
        self, 
        interactions: torch.Tensor, 
        additional_embeddings: Dict[str, torch.Tensor] = {},
        continuous_features: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        users, items = interactions.T
    
        all_embed = torch.cat([
            self.users_emb(users), # Receives the indices
            self.items_emb(items),
            *[ emb(additional_embeddings[k]) for k, emb in self.additional_embs.items() ]
        ], dim=1)

        # TODO: Use hashing to avoid problems with biased distributions
        cross_product_idx = (users*self.n_items + items) % self.hparams.crossed_feat_dim
        cross_product = nn.functional.one_hot(cross_product_idx, self.hparams.crossed_feat_dim)

        if self.hparams.dnn_cont_features > 0:
            deep_input = torch.cat([continuous_features, all_embed], dim=1)
        else:
            deep_input = all_embed

        return self.head(torch.cat([
            cross_product, # wide input
            self.deep(deep_input), # deep output
        ], dim=1))


class WideAndDeep(object):
    def __init__(
        self, 
        data,
        hparams: WideAndDeepHyperParams = WideAndDeepHyperParams(),
        seed=None,
    ):
        self.model = WideAndDeepModel(
            num_users=...,
            num_items=...,
            hparams=hparams,
        )
        self.dataloader = DataLoader(...)
        self.loss_fn = nn.CrossEntropyLoss()
        
    def fit(self):
        self.train_loop()
        self.test_loop()

    def train_loop(self):
        self.model.train()
        
        for batch, (X,y) in enumerate(self.dataloader):
            pred = self.model(X)
            loss = self.loss_fn(pred, y)

            # Propagate error
            loss.backward()
            self.optimizer.step()
            self.optimizer.zero_grad()

    def test_loop(self):
        # TODO: Copypasted example from pytorch's tutorial. Might need complete rewritting.
        self.model.eval()
        
        size = len(self.dataloader.dataset)
        num_batches = len(self.dataloader)
        test_loss, correct = 0, 0

        with torch.no_grad():
            for X, y in self.dataloader:
                pred = self.model(X)
                test_loss += self.loss_fn(pred, y).item()
                correct += (pred.argmax(1) == y).type(torch.float).sum().item()

        test_loss /= num_batches
        correct /= size
