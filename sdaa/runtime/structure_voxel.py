"""CPU default 28-channel Gnina grid for DEVELOP generation (no augmentation).

Atom typing, default receptor/ligand maps and piecewise density follow
gnina/libmolgrid src/atom_typer.cpp and grid_maker.cpp. This implementation
uses the target Open Babel Python binding, not a CUDA-linked molgrid wheel.
Default grid: 23.5 Angstrom, 0.5 spacing, Gaussian radius multiplier 1.
"""
from pathlib import Path
import numpy as np
from openbabel import openbabel as ob

RADII = np.array([.37,.37,1.9,1.9,1.9,1.9,1.8,1.8,1.8,1.8,1.7,1.7,1.7,1.7,
                  2.,2.,2.1,1.5,1.8,2.,2.2,1.2,1.2,1.2,1.2,1.2,1.2,1.92], dtype=np.float32)
REC = [-1,-1,0,1,2,3,5,6,6,5,7,8,8,7,9,9,10,4,4,4,4,13,13,12,11,13,13,13]
LIG = [-1,-1,0,1,2,3,7,8,8,7,9,10,10,9,11,11,12,6,5,4,4,13,13,13,13,13,13,13]


def atom_type(atom):
    neighbors = list(ob.OBAtomAtomIter(atom))
    hydrogen = any(a.GetAtomicNum() == 1 for a in neighbors)
    hetero = any(a.GetAtomicNum() not in (1, 6) for a in neighbors)
    n = atom.GetAtomicNum()
    if n == 1:
        return int(atom.IsPolarHydrogen())
    if n == 6:
        return (4 if atom.IsAromatic() else 2) + int(hetero)
    if n == 7:
        return (8 if hydrogen else 9) if atom.IsHbondAcceptor() else (7 if hydrogen else 6)
    if n == 8:
        return 12 if hydrogen else 13
    if n in (16, 34):
        return 15 if n == 16 and atom.IsHbondAcceptor() else 14
    return {5:27,9:17,12:21,15:16,17:18,20:24,25:22,26:25,30:23,35:19,53:20}.get(n,26)


def coordinates(path, ligand):
    conversion, mol = ob.OBConversion(), ob.OBMol()
    if not conversion.ReadFile(mol, str(path)):
        raise ValueError("Cannot read molecule: " + str(path))
    mol.AddHydrogens()
    mapping = LIG if ligand else REC
    xyz, types, radii = [], [], []
    for atom in ob.OBMolAtomIter(mol):
        raw = atom_type(atom)
        channel = mapping[raw]
        if channel >= 0:
            xyz.append([atom.GetX(), atom.GetY(), atom.GetZ()])
            types.append(channel)
            radii.append(RADII[raw])
    return np.asarray(xyz, dtype=np.float32), types, radii


def grid(types_line, data_root):
    fields = types_line.split()
    if len(fields) != 3:
        raise ValueError("Expected one label and receptor/ligand SDF paths")
    sets = [coordinates(Path(data_root)/name, ligand=i==1) for i,name in enumerate(fields[1:])]
    if not len(sets[-1][0]):
        raise ValueError("Empty ligand coordinate set")
    # Match sequential float32 accumulation in CoordinateSet::center.
    center = np.zeros(3, dtype=np.float32)
    for xyz in sets[-1][0]:
        center += xyz
    center /= np.float32(len(sets[-1][0]))
    origin = center - np.float32(23.5/2)
    out = np.zeros((28,48,48,48), dtype=np.float32)
    e = np.float32(np.exp(-2.))
    A,B,C = np.float32(4*e),np.float32(-12*e),np.float32(9*e)
    for i,(coords, channels, radii) in enumerate(sets):
        for xyz,channel,radius in zip(coords,channels,radii):
            reach = radius*np.float32(1.5)
            low = np.maximum(0,np.floor((xyz-reach-origin)/np.float32(.5)).astype(int))
            high = np.minimum(48,np.ceil((xyz+reach-origin)/np.float32(.5)).astype(int)+1)
            if np.any(high <= low):
                continue
            axes = [origin[j]+np.arange(low[j],high[j],dtype=np.float32)*np.float32(.5)-xyz[j] for j in range(3)]
            r2 = axes[0][:,None,None]**2 + axes[1][None,:,None]**2 + axes[2][None,None,:]**2
            dr = np.sqrt(r2)/radius
            density = np.where(dr <= 1, np.exp(-2*r2/(radius*radius)),
                               np.maximum(0,(A*dr+B)*dr+C))
            density[dr >= 1.5] = 0
            out[channel+14*i,low[0]:high[0],low[1]:high[1],low[2]:high[2]] += density
    return out
