"""Inference translation of DEVELOP.py's pretrained residual GGNN and 3D CNN.

Uses the original TF1 checkpoint arrays directly, without retraining. TF1 GRU
uses reset-before-matmul and (reset, update) gates, unlike torch.nn.GRUCell.
Only generation is implemented; the original TensorFlow training path remains.
"""
import pickle
import os
from pathlib import Path

# Use 1 explicitly when replaying strict FP32 numerical comparisons.
os.environ.setdefault("TORCH_SDAA_CONV_USE_FP32", "0")

import numpy as np
import torch
import torch.nn.functional as F


class DevelopInference:
    def __init__(self, checkpoint, device="cpu"):
        self.device = torch.device(device)
        with Path(checkpoint).open("rb") as stream:
            saved = pickle.load(stream)  # Official project checkpoint, trusted input.
        self.weights = {
            name: torch.from_numpy(np.asarray(value, dtype=np.float32).copy()).to(self.device)
            for name, value in saved["weights"].items()
            if "/Adam" not in name and name not in ("beta1_power:0", "beta2_power:0")
        }
        if len(self.weights) != 123:
            raise ValueError("Expected the 123 pretrained DEVELOP model tensors")
        # The public linker/scaffold checkpoints use five structural values;
        # the pharmacophore checkpoint uses nine. Infer the head width from
        # original arrays rather than silently truncating or padding inputs.
        self.struct_data_len = (int(self.var(11).shape[0])
                                - int(self.var(0).shape[0])
                                - int(self.var(38).shape[1]) - 1)
        if self.struct_data_len not in (5, 9):
            raise ValueError("Unsupported pretrained structural feature width: "
                             + str(self.struct_data_len))
        declared = saved.get("params", {}).get("struct_data_len")
        if declared is not None and declared != self.struct_data_len:
            raise ValueError("Checkpoint parameters disagree with original head shapes")
        self.cached_input = None
        self.cached_pool = None
        self.residuals = {2: [0], 4: [0, 2], 6: [0, 2, 4]}
        self.convs = [self.var(32 + 2*i).permute(4, 3, 0, 1, 2).contiguous() for i in range(3)]

    def var(self, index):
        suffix = "" if index == 0 else "_" + str(index)
        return self.weights["graph_model/Variable" + suffix + ":0"]

    def tensor(self, value, integer=False):
        return torch.as_tensor(np.asarray(value), dtype=torch.long if integer else torch.float32,
                               device=self.device)

    def ggnn(self, h, adjacency, decoder=False):
        b, v, d = h.shape
        h = h.reshape(-1, d)
        states = [h]
        for i in range(7):
            scope = "gru_scope_" + ("decoder" if decoder else "encoder") + str(i)
            message_scope = "graph_model/" + scope + "/"
            ew = self.weights[message_scope + "Variable:0"]
            eb = self.weights[message_scope + "Variable_1:0"]
            acts = None
            for edge in range(3):
                msg = (h @ ew[edge] + eb[edge]).reshape(b, v, d)
                term = adjacency[:, edge] @ msg
                acts = term if acts is None else acts + term
            acts = torch.cat([acts.reshape(-1, d)] + [states[j] for j in self.residuals.get(i, [])], -1)
            prefix = ("" if decoder else "graph_model/") + scope + "/gru_cell/"
            r, u = torch.sigmoid(torch.cat([acts, h], -1) @ self.weights[prefix + "gates/kernel:0"]
                                 + self.weights[prefix + "gates/bias:0"]).chunk(2, -1)
            candidate = torch.tanh(torch.cat([acts, r*h], -1) @ self.weights[prefix + "candidate/kernel:0"]
                                   + self.weights[prefix + "candidate/bias:0"])
            h = u*h + (1-u)*candidate
            states.append(h)
        return h.reshape(b, v, d)

    def cnn_pool(self, x):
        for i in range(3):
            x = F.relu(F.conv3d(x, self.convs[i], self.var(33+2*i), padding=1))
            if i < 2:
                x = F.max_pool3d(x, 2, 2, ceil_mode=True)
        x = torch.amax(x, dim=(2, 3, 4))
        return x

    @torch.inference_mode()
    def cache_structure(self, value):
        """Reuse deterministic convolution features for this exact input object.

        Used only during autoregressive sampling, never by the fixed-forward
        benchmark. Dropout remains freshly sampled on every predict call.
        """
        self.cached_input = value
        self.cached_pool = self.cnn_pool(self.tensor(value))

    def cnn(self, x, dropout_uniform=None, pooled=None):
        x = self.cnn_pool(x) if pooled is None else pooled
        # TF1 rate=.2 uses floor(.8 + uniform), also in generation mode.
        if dropout_uniform is None:
            dropout_uniform = torch.rand(x.shape, device=self.device)
        x = (x / .8) * torch.floor(.8 + dropout_uniform)
        return x @ self.var(38)

    def latent(self, f):
        mask_in, mask_out = f["node_mask_in"].unsqueeze(-1), f["node_mask_out"].unsqueeze(-1)
        embeddings = F.embedding(f["initial_node_representation_in"].argmax(-1), self.var(31)) * mask_in
        h = self.ggnn(embeddings, f["adjacency_matrix_in"])
        mean = (h @ self.var(0) + self.var(1)) * mask_in + f["z_prior_in"] * (1-mask_in)
        c, y = mean @ self.var(9), mean @ self.var(10)
        masks = (mask_out.unsqueeze(2)*1e10-1e10) + (mask_out.unsqueeze(1)*1e10-1e10)
        attention = torch.sigmoid(c.unsqueeze(2) + y.unsqueeze(1) + masks).sum(2) / mask_out.sum(1).unsqueeze(1)
        return mean*mask_out + attention*(f["z_prior"] @ self.var(8))

    def node_symbols(self, f, z, cnn):
        mi, mo = f["node_mask_in"].unsqueeze(-1), f["node_mask_out"].unsqueeze(-1)
        b, v, _ = z.shape
        count = (mo-mi).sum(1).unsqueeze(1).expand(b, v, 1)
        z = torch.cat([z, f["abs_dist"].unsqueeze(1).expand(b, v, -1), count,
                       cnn.unsqueeze(1).expand(b, v, -1)], -1)
        masks = ((mo-mi).unsqueeze(2)*1e10-1e10) + ((mo-mi).unsqueeze(1)*1e10-1e10)
        attention = torch.sigmoid((z @ self.var(12)).unsqueeze(2) +
                                  (z @ self.var(13)).unsqueeze(1) + masks).sum(2) / mo.sum(1).unsqueeze(1)
        z = z*mi + attention*(z @ self.var(11))
        return torch.softmax(z @ self.var(14) + self.var(15), -1)

    def fc(self, x, index):
        return F.relu(x @ self.var(index) + self.var(index+1)) @ self.var(index+2)

    def edges(self, f, z, cnn):
        b, v, _ = z.shape
        seq = f["node_sequence_out"][:, 0].unsqueeze(-1)
        emb = F.embedding(f["latent_node_symbols_out"].argmax(-1), self.var(31)) * f["node_mask_out"].unsqueeze(-1)
        initial = torch.cat([z, emb, seq], -1)
        h = self.ggnn(initial, f["incre_adj_mat_out"][:, 0], decoder=True) * f["node_mask_out"].unsqueeze(-1)
        focus = (seq*h).sum(1)
        denom = f["node_mask_out"].sum(1, keepdim=True)
        local, glob = h.sum(1)/denom, initial.sum(1)/denom
        dist = F.embedding(f["distance_to_others_out"][:, 0].long(), self.var(29))
        overlap = F.embedding(f["overlapped_edge_features_out"][:, 0].long(), self.var(30))
        expand = lambda x: x.unsqueeze(1).expand(b, v, -1)
        iteration = f["it_num"].reshape(b, 1)
        pos = torch.cat([f["abs_dist"], iteration, cnn], -1)
        combined = torch.cat([expand(focus), h, expand(local), expand(glob), dist, overlap, expand(pos)], -1)
        stop = torch.cat([focus, self.var(28).expand(b, -1), local, glob,
                          self.var(29)[0].expand(b, -1), self.var(30)[0].expand(b, -1), pos], -1)
        logits = self.fc(combined, 25).squeeze(-1) + (f["edge_masks_out"][:, 0]*1e10-1e10)
        logits = torch.cat([logits, self.fc(stop, 25)], -1)
        types = torch.stack([self.fc(combined, 16+3*i).squeeze(-1) for i in range(3)], 1)
        types = types + (f["edge_type_masks_out"][:, 0]*1e10-1e10)
        return torch.softmax(logits, -1), torch.softmax(types, 1)

    @torch.inference_mode()
    def predict(self, feeds, kind):
        if np.asarray(feeds["abs_dist"]).shape[-1] != self.struct_data_len:
            raise ValueError("Structural input must have " + str(self.struct_data_len)
                             + " values for this checkpoint")
        required = ["node_mask_in", "node_mask_out", "initial_node_representation_in", "adjacency_matrix_in",
                    "z_prior", "z_prior_in", "abs_dist", "cnn_input"]
        if kind == "edges":
            required += ["node_sequence_out", "latent_node_symbols_out", "incre_adj_mat_out", "distance_to_others_out",
                         "overlapped_edge_features_out", "it_num", "edge_masks_out", "edge_type_masks_out"]
        cached = feeds["cnn_input"] is self.cached_input
        f = {k: self.tensor(feeds[k]) for k in required if k != "cnn_input" or not cached}
        uniform = feeds.get("dropout_uniform")
        cnn = self.cnn(f.get("cnn_input"), None if uniform is None else self.tensor(uniform),
                       self.cached_pool if cached else None)
        z = self.latent(f)
        result = (self.node_symbols(f, z, cnn),) if kind == "node_symbols" else self.edges(f, z, cnn)
        return tuple(x.cpu().numpy() for x in result)


def captured_feed(frame, arrays):
    """Translate captured TF placeholder names into the original Python keys."""
    rename = {"node_features_in": "initial_node_representation_in", "node_features_out": "initial_node_representation_out",
              "latent_node_symbol_out": "latent_node_symbols_out"}
    feed = {}
    for binding in frame["input_bindings"]:
        name = binding["tensor"].split(":")[0].split("/")[-1]
        if binding["tensor"].startswith("test/dropout/"):
            name = "dropout_uniform"
        feed[rename.get(name, name)] = arrays[binding["array"]]
    return feed
