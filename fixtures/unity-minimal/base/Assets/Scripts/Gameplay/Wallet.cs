namespace ChangeLens.Fixture
{
    public sealed class Wallet
    {
        public bool IsLocked { get; set; }
        public int Balance { get; private set; }

        public void ResetDaily() => IsLocked = false;

        public void Credit(int amount)
        {
            Balance += amount;
        }
    }
}

