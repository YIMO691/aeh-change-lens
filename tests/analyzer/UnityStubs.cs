using System;

namespace UnityEngine
{
    public class Object { }
    public class ScriptableObject : Object { }
    public class MonoBehaviour : Object
    {
        protected void SendMessage(string name, object value, SendMessageOptions options) { }
    }
    public sealed class SerializeField : Attribute { }
    public static class Debug { public static void Log(object value) { } }
    public enum SendMessageOptions { RequireReceiver, DontRequireReceiver }
}

namespace UnityEngine.Events
{
    public abstract class UnityEventBase { }
    public class UnityEvent<T> : UnityEventBase { public void Invoke(T value) { } }
}

