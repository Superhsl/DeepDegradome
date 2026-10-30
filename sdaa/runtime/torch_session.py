"""Connect the original DEVELOP graph sampler to source-based torch inference."""
from contextlib import nullcontext
from collections import defaultdict
import torch
from rdkit import Chem
from .torch_inference import DevelopInference
from .structure_voxel import grid


class InferenceGraph:
    def as_default(self):
        return nullcontext()


class InferenceSession:
    def __init__(self, checkpoint, device):
        if device == "sdaa":
            import torch_sdaa
            if not torch.sdaa.is_available():
                raise RuntimeError("SDAA device unavailable")
        self.model = DevelopInference(checkpoint, device)
        self.calls = {"node_symbols": 0, "edges": 0}

    def run(self, fetches, feed_dict):
        expected_node = ["node_symbol_prob_in"]
        expected_edge = ["edge_predictions_in", "edge_type_predictions_in"]
        if fetches == expected_node:
            kind = "node_symbols"
        elif fetches == expected_edge:
            kind = "edges"
        else:
            raise NotImplementedError("Torch backend supports generation inference fetches only")
        self.calls[kind] += 1
        return list(self.model.predict(feed_dict, kind))


def initialize(model, args):
    if not model.params["generation"]:
        raise NotImplementedError("Torch backend currently supports generation, not training")
    if not args.get("--restore"):
        raise ValueError("Original pretrained checkpoint is required")
    session = InferenceSession(args["--restore"], args["--torch-device"])
    expected = {"hidden_size":32,"encoding_size":4,"num_timesteps":7,"num_symbols":14,
                "struct_data_len":session.model.struct_data_len,"residual_connection_on":True,
                "use_graph":True,"use_edge_bias":True,"cnn_ligand_only":False}
    for key,value in expected.items():
        if model.params[key] != value:
            raise ValueError("Pretrained torch architecture requires " + key + "=" + str(value))
    # Symbolic feed keys let the unchanged get_dynamic_feed_dict/sampler run.
    model.placeholders = defaultdict(lambda: None)
    keys = ["z_prior","z_prior_in","incre_adj_mat_out","num_vertices","initial_node_representation_in",
            "initial_node_representation_out","node_symbols_out","node_symbols_in","latent_node_symbols_in",
            "latent_node_symbols_out","adjacency_matrix_in","adjacency_matrix_out","vertices_to_keep",
            "exit_points","abs_dist","it_num","sdf_idx","node_mask_in","node_mask_out","graph_state_keep_prob",
            "edge_weight_dropout_keep_prob","iteration_mask_out","is_generative","out_layer_dropout_keep_prob",
            "distance_to_others_out","overlapped_edge_features_out","max_iteration_num","node_sequence_out",
            "edge_type_masks_out","edge_masks_out","cnn_input"]
    model.placeholders = {k:k for k in keys}
    model.ops = {k:k for k in ["node_symbol_prob_in","edge_predictions_in","edge_type_predictions_in"]}
    model.graph = InferenceGraph()
    model.sess = session
    torch.manual_seed(model.params["random_seed"])
    if args["--torch-device"] == "sdaa":
        torch.sdaa.manual_seed_all(model.params["random_seed"])


def generate_from_structures(model, data, struct_data):
    """Same bucket/latent/sampler order as generate_new_graphs; CPU voxel stage."""
    from utils import generate_std_normal, dump
    bucketed, bucket_sizes, bucket_at_step = data
    counters = defaultdict(int)
    generated = []
    count = 0
    for bucket in bucket_at_step:
        start = counters[bucket]*model.params["batch_size"]
        elements_batch = bucketed[bucket][start:start+model.params["batch_size"]]
        for elements in elements_batch:
            cnn = grid(struct_data[elements["sdf_idx"]], model.params["struct_data_root"])
            if model.params["cnn_ligand_only"]:
                raise NotImplementedError("Original checkpoint uses all 28 channels")
            maximum = model.compensate_node_length(elements,bucket_sizes[bucket])
            cnn_input = cnn[None]
            model.sess.model.cache_structure(cnn_input)
            for _ in range(model.params["number_of_generation_per_valid"]):
                z = generate_std_normal(1,maximum,model.params["encoding_size"])
                zi = generate_std_normal(1,maximum,model.params["hidden_size"])
                model.generate_graph_with_state(z,zi,maximum,generated,elements,count,cnn_input)
                count += 1
        counters[bucket] += 1
    name = (model.params["output_name"]+"_generated_smiles.smi") if model.params["output_name"] else (model.run_id+"_generated_smiles_"+model.params["dataset"]+".smi")
    with open(name,"w") as out:
        out.writelines(line+"\n" for line in generated)
    parsed = sum(Chem.MolFromSmiles(line.split()[-1]) is not None for line in generated)
    print("Generation done",{"attempted":count,"generated":len(generated),"parseable":parsed,"neural_calls":model.sess.calls},flush=True)
    if not generated or parsed != len(generated):
        raise RuntimeError("No valid generated molecules")
