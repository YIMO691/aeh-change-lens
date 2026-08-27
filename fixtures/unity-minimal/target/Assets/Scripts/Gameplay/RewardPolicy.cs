using UnityEngine;

namespace ChangeLens.Fixture
{
    public sealed class RewardPolicy : ScriptableObject
    {
        public int CalculateBonus(int amount)
        {
            return amount >= 100 ? 10 : 0;
        }
    }
}

