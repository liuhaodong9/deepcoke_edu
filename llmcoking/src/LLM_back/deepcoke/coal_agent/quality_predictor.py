"""焦炭质量预测 - 多模型支持 (RF/SVR/KNN/Linear/DecisionTree/GBR)"""

import os
import pickle
import numpy as np

MODEL_DIR = os.path.dirname(__file__)

X_MIN = np.array([0.68, 7.03, 21.36, 0.15, 56.46, 16.00, 11.63])
X_MAX = np.array([12.024, 21.660, 39.800, 4.410, 103.000, 41.000, 31.000])


def _load(filename):
    with open(os.path.join(MODEL_DIR, filename), "rb") as f:
        return pickle.load(f)


class QualityPredictor:
    def __init__(self):
        self.models = {}
        for name, fname in [
            ("RF", "RF.pickle"), ("KNN", "KNN.pickle"),
            ("Linear", "linear.pickle"), ("DecisionTree", "decisiontree.pickle"),
            ("SVR_CRI", "SVR_CRI.pickle"), ("SVR_CSR", "SVR_CSR.pickle"),
            ("GBR_1", "GradientBoostingRegressor_1.pickle"),
            ("GBR_2", "GradientBoostingRegressor_2.pickle"),
        ]:
            try:
                self.models[name] = _load(fname)
            except Exception as e:
                print(f"[coal_agent] {name} load failed: {e}")

    def predict(self, blend_ratios: dict, coal_props: dict, model_name: str = "RF") -> dict:
        """
        Args:
            blend_ratios: {"红果": 30, "晋茂": 40, ...} (百分比)
            coal_props: 煤样属性字典 {name: {coal_mad, Ad, Vdaf, coal_std, G, X, Y, ...}}
            model_name: RF/SVR/KNN/Linear/DecisionTree/GBR
        """
        features = np.zeros(7)
        total = sum(blend_ratios.values())
        for name, pct in blend_ratios.items():
            if name not in coal_props:
                continue
            p = coal_props[name]
            r = pct / total
            features += r * np.array([
                p.get("coal_mad", 0), p.get("Ad", 0), p.get("Vdaf", 0),
                p.get("coal_std", 0), p.get("G", 0), p.get("X", 0), p.get("Y", 0),
            ])

        norm = ((features - X_MIN) / (X_MAX - X_MIN)).reshape(1, -1)

        result = {"model": model_name, "Ad": round(float(features[1]), 2)}

        if model_name == "SVR" and "SVR_CRI" in self.models:
            result["CRI"] = round(float(self.models["SVR_CRI"].predict(norm)[0]), 2)
            result["CSR"] = round(float(self.models["SVR_CSR"].predict(norm)[0]), 2)
        elif model_name == "GBR" and "GBR_1" in self.models:
            result["CRI"] = round(float(self.models["GBR_1"].predict(norm)[0]), 2)
            result["CSR"] = round(float(self.models["GBR_2"].predict(norm)[0]), 2)
        elif model_name in self.models:
            pred = np.around(self.models[model_name].predict(norm).astype(float), 2)[0]
            result["CRI"] = float(pred[0])
            result["CSR"] = float(pred[1])
        else:
            result["error"] = f"Model '{model_name}' not available"

        return result

    def available_models(self):
        names = []
        for k in self.models:
            base = k.split("_")[0]
            if base not in names:
                names.append(base)
        return names


predictor = QualityPredictor()
